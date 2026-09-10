import logging
import time
from dataclasses import dataclass

from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError

from config.settings import GEMINI_API_KEY
from agent.state import SessionState
from agent.prompts import build_system_prompt
from agent.tools import TOOL_DECLARATIONS, ToolExecutor
from integrations.google_calendar import CalendarClient
from integrations.google_sheets import SheetsClient

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_DELAY = 10  # seconds

MAX_TOOL_ROUNDS = 5  # Max tool-call round-trips per user message


@dataclass
class AgentResponse:
    text: str
    session: SessionState
    tools_called: list[str]


class ReceptionistAgent:
    def __init__(
        self,
        calendar_client: CalendarClient,
        sheets_client: SheetsClient,
        model_name: str = "gemini-2.5-flash",
    ):
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.model_name = model_name
        self.tool_executor = ToolExecutor(calendar_client, sheets_client)

        # Build tool declarations for Gemini
        self.tool_declarations = [
            types.FunctionDeclaration(
                name=td["name"],
                description=td["description"],
                parameters=td["parameters"],
            )
            for td in TOOL_DECLARATIONS
        ]
        self.tools = types.Tool(function_declarations=self.tool_declarations)

    def _generate_with_retry(self, contents, config):
        """Call Gemini with retry on rate limit (429) and server (503) errors."""
        for attempt in range(MAX_RETRIES):
            try:
                return self.client.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=config,
                )
            except (ClientError, ServerError) as e:
                code = getattr(e, "code", None)
                if code in (429, 503) and attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning("API error (%s). Retrying in %ds (attempt %d/%d)", code, delay, attempt + 1, MAX_RETRIES)
                    time.sleep(delay)
                else:
                    raise

    def process_message(
        self,
        message: str,
        history: list[dict],
        session: SessionState,
        is_voice: bool = False,
    ) -> AgentResponse:
        """
        Process a single user message and return the agent's response.

        Args:
            message: The user's message text.
            history: Conversation history as list of types.Content objects.
            session: Current session state.
            is_voice: If True, use voice-optimized prompts.

        Returns:
            AgentResponse with text, updated session, and list of tools called.
        """
        system_prompt = build_system_prompt(session, is_voice=is_voice)
        tools_called = []

        try:
            # Build full contents: history + new user message
            contents = list(history) + [
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=message)],
                )
            ]

            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=[self.tools],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True,
                ),
            )

            # Initial call
            response = self._generate_with_retry(contents, config)

            # Handle tool call loop
            round_count = 0
            while round_count < MAX_TOOL_ROUNDS:
                # Check for function calls
                function_calls = []
                if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                    function_calls = [
                        part for part in response.candidates[0].content.parts
                        if part.function_call and part.function_call.name
                    ]

                if not function_calls:
                    break

                # Add the assistant's function call message to contents
                contents.append(response.candidates[0].content)

                # Execute each function call and build responses
                function_response_parts = []
                for fc in function_calls:
                    tool_name = fc.function_call.name
                    tool_args = dict(fc.function_call.args) if fc.function_call.args else {}
                    tools_called.append(tool_name)

                    # Resolve event IDs from cached appointments (LLM often fabricates them)
                    if tool_name == "cancel_appointment" and session.fetched_appointments:
                        tool_args["event_id"], tool_args["groomer_name"] = self._resolve_event_id(
                            tool_args.get("event_id", ""),
                            tool_args.get("groomer_name", ""),
                            session.fetched_appointments,
                        )
                    elif tool_name == "reschedule_appointment" and session.fetched_appointments:
                        tool_args["old_event_id"], tool_args["old_groomer_name"] = self._resolve_event_id(
                            tool_args.get("old_event_id", ""),
                            tool_args.get("old_groomer_name", ""),
                            session.fetched_appointments,
                        )

                    logger.info("Tool call: %s(%s)", tool_name, tool_args)

                    # Execute the tool
                    result = self.tool_executor.execute(tool_name, tool_args)

                    # Update session state based on tool results
                    self._update_session(session, tool_name, tool_args, result)

                    function_response_parts.append(
                        types.Part.from_function_response(
                            name=tool_name,
                            response=result,
                        )
                    )

                # Add tool results to contents and call Gemini again
                contents.append(
                    types.Content(role="user", parts=function_response_parts)
                )

                response = self._generate_with_retry(contents, config)
                round_count += 1

            # Extract text response
            response_text = ""
            if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.text:
                        response_text += part.text

            if not response_text:
                response_text = "I'm sorry, I didn't quite get that. Could you say that again?"

            # Update history in place for caller to persist
            # (the caller's history list is separate, they manage it)

            return AgentResponse(
                text=response_text.strip(),
                session=session,
                tools_called=tools_called,
            )

        except Exception as e:
            logger.exception("Agent processing error")
            fallback = (
                "I'm having some technical difficulties right now. "
                "Could you please call back in a few minutes, or I can have someone call you back?"
            )
            return AgentResponse(text=fallback, session=session, tools_called=tools_called)

    @staticmethod
    def _resolve_event_id(
        llm_event_id: str, llm_groomer: str, appointments: list[dict]
    ) -> tuple[str, str]:
        """Resolve a possibly fabricated event_id to the real one from cached appointments.

        Strategy:
        1. If the LLM's event_id matches a real one, use it.
        2. Otherwise, match by groomer name.
        3. If only one appointment exists, use that.
        4. Fall back to the LLM's values (will fail with 404, but at least we tried).
        """
        # Check if LLM gave us a real event_id
        real_ids = {a["event_id"] for a in appointments}
        if llm_event_id in real_ids:
            # Also verify/fix groomer
            for a in appointments:
                if a["event_id"] == llm_event_id:
                    return llm_event_id, a["groomer_name"]
            return llm_event_id, llm_groomer

        # Match by groomer name
        groomer_matches = [a for a in appointments if a["groomer_name"].lower() == llm_groomer.lower()]
        if len(groomer_matches) == 1:
            match = groomer_matches[0]
            logger.warning(
                "Resolved fabricated event_id '%s' → '%s' (matched by groomer '%s')",
                llm_event_id, match["event_id"], llm_groomer,
            )
            return match["event_id"], match["groomer_name"]

        # If only one appointment total, use it
        if len(appointments) == 1:
            match = appointments[0]
            logger.warning(
                "Resolved fabricated event_id '%s' → '%s' (only one appointment)",
                llm_event_id, match["event_id"],
            )
            return match["event_id"], match["groomer_name"]

        # Multiple matches by groomer — can't determine which one, fall back
        logger.warning("Could not resolve fabricated event_id '%s' — %d appointments for groomer '%s'",
                        llm_event_id, len(groomer_matches), llm_groomer)
        return llm_event_id, llm_groomer

    def _update_session(
        self, session: SessionState, tool_name: str, args: dict, result: dict
    ):
        """Update session state based on tool call results."""
        if tool_name == "lookup_contact":
            phone = args.get("phone", "")
            session.phone = phone
            if result.get("found"):
                session.identified = True
                session.contact_records = result.get("contacts", [])
                if session.contact_records:
                    first = session.contact_records[0]
                    session.name = first.get("Name", "")
                    if len(session.contact_records) == 1:
                        session.dog_name = first.get("Dog Name")
                        session.dog_breed = first.get("Dog Breed")
                        session.dog_size = first.get("Dog Size")

        elif tool_name == "register_contact":
            session.phone = args.get("phone", session.phone)
            session.name = args.get("name", session.name)
            session.dog_name = args.get("dog_name", session.dog_name)
            session.dog_breed = args.get("dog_breed", session.dog_breed)
            session.dog_size = args.get("dog_size", session.dog_size)
            session.identified = True

        elif tool_name == "book_appointment":
            if result.get("success"):
                event_id = result.get("event_id", "")
                if event_id:
                    session.booked_event_ids.append(event_id)
                summary = (
                    f"Booked {args.get('service_name')} for {args.get('dog_name')} "
                    f"on {args.get('date')} at {args.get('time')} with {args.get('groomer_name')}. "
                    f"₹{result.get('price', '?')}"
                )
                session.call_summary_parts.append(summary)
                session.current_intent = "book"
                session.intents_completed.append("book")

        elif tool_name == "reschedule_appointment":
            # Capture phone/name from args if session doesn't have them
            if not session.phone and args.get("phone"):
                session.phone = args["phone"]
            if not session.name and args.get("customer_name"):
                session.name = args["customer_name"]
            if result.get("success"):
                summary = (
                    f"Rescheduled to {args.get('new_date')} at {args.get('new_time')} "
                    f"with {args.get('new_groomer_name')}"
                )
                session.call_summary_parts.append(summary)
                session.intents_completed.append("reschedule")

        elif tool_name == "cancel_appointment":
            if result.get("success"):
                session.call_summary_parts.append("Cancelled appointment")
                session.intents_completed.append("cancel")

        elif tool_name == "escalate_to_staff":
            reason = args.get("reason", "Unknown")
            if not session.phone and args.get("phone"):
                session.phone = args["phone"]
            if not session.name and args.get("caller_name"):
                session.name = args["caller_name"]
            session.call_summary_parts.append(f"Escalated: {reason}")
            session.intents_completed.append("escalation")

        elif tool_name == "check_availability":
            # Track that a booking was attempted (helps with logging if user abandons)
            if not session.current_intent:
                session.current_intent = "book"

        elif tool_name == "get_upcoming_appointments":
            # Set phone from args so it's available for logging
            if not session.phone and args.get("phone"):
                session.phone = args["phone"]
            # Cache appointments so cancel/reschedule can resolve real event IDs
            if result.get("found"):
                session.fetched_appointments = result.get("appointments", [])
            # Extract caller name from appointment data if not already known
            if not session.name and result.get("found"):
                appointments = result.get("appointments", [])
                if appointments:
                    desc = appointments[0].get("description", "")
                    for line in desc.split("\n"):
                        if line.startswith("Customer: "):
                            session.name = line[len("Customer: "):]
                            break


def create_agent(
    calendar_client: CalendarClient,
    sheets_client: SheetsClient,
    model_name: str = "gemini-2.5-flash",
) -> ReceptionistAgent:
    """Factory function to create a configured ReceptionistAgent."""
    return ReceptionistAgent(
        calendar_client=calendar_client,
        sheets_client=sheets_client,
        model_name=model_name,
    )
