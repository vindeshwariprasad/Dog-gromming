"""
Phase 1: Streamlit chat interface for the AI Receptionist.

Run with: streamlit run ui/streamlit_app.py
"""

import sys
import os
import logging

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from google.genai import types

from integrations.auth import get_google_credentials
from integrations.google_calendar import CalendarClient
from integrations.google_sheets import SheetsClient
from agent.core import create_agent
from agent.state import SessionState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


@st.cache_resource
def init_clients():
    """Initialize shared clients (cached across reruns)."""
    credentials = get_google_credentials()
    calendar_client = CalendarClient(credentials)
    sheets_client = SheetsClient(credentials)
    agent = create_agent(calendar_client, sheets_client)
    return agent, sheets_client


def log_previous_call(sheets_client: SheetsClient, session: SessionState, message_count: int = 0):
    """Log the completed conversation to the Call Log tab."""
    # Skip if user never sent a message (only initial greeting exists)
    if message_count < 2:
        return

    if session.intents_completed:
        intent = ", ".join(session.intents_completed)
    elif session.current_intent:
        intent = f"{session.current_intent} (abandoned)"
    else:
        intent = "General"
    summary = session.get_call_summary() or "FAQ / general enquiry"

    sheets_client.log_call(
        phone=session.phone or "",
        caller_name=session.name or "",
        intent=intent,
        summary=summary,
        outcome="Completed",
    )
    logger.info("Auto-logged call: %s / %s", session.phone, intent)


def convert_history_for_gemini(messages: list[dict]) -> list:
    """Convert Streamlit message history to Gemini Content format."""
    history = []
    for msg in messages:
        role = "user" if msg["role"] == "user" else "model"
        history.append(
            types.Content(
                role=role,
                parts=[types.Part.from_text(text=msg["content"])],
            )
        )
    return history


def main():
    st.set_page_config(
        page_title="Maple Street Dog Grooming - AI Receptionist",
        page_icon="\U0001f43e",
        layout="centered",
    )

    st.title("Maple Street Dog Grooming")
    st.caption("AI Receptionist \u2014 Phase 1 Chat")

    # Initialize agent and clients
    agent, sheets_client = init_clients()

    # Initialize session state
    if "messages" not in st.session_state:
        st.session_state.messages = []
        st.session_state.session = SessionState()
        st.session_state.call_logged = False
        greeting = (
            "Hi! Welcome to Maple Street Dog Grooming. How can I help you today?"
        )
        st.session_state.messages.append({"role": "assistant", "content": greeting})

    # New conversation button — log the previous call before resetting
    if st.sidebar.button("New Conversation"):
        if not st.session_state.get("call_logged"):
            log_previous_call(sheets_client, st.session_state.session, len(st.session_state.messages))
        st.session_state.messages = []
        st.session_state.session = SessionState()
        st.session_state.call_logged = False
        greeting = (
            "Hi! Welcome to Maple Street Dog Grooming. How can I help you today?"
        )
        st.session_state.messages.append({"role": "assistant", "content": greeting})
        st.rerun()

    # Display sidebar info
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Session Info**")
    session = st.session_state.session
    if session.identified:
        st.sidebar.markdown(f"Caller: {session.name}")
        st.sidebar.markdown(f"Phone: {session.phone}")
        if session.dog_name:
            st.sidebar.markdown(f"Dog: {session.dog_name}")
    else:
        st.sidebar.markdown("Caller: Not identified")

    if session.intents_completed:
        st.sidebar.markdown(f"Completed: {', '.join(session.intents_completed)}")

    # Display chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat input
    if user_input := st.chat_input("Type your message..."):
        # Display user message
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        # Get agent response
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                # Build history: all messages except the new user message
                history_for_gemini = convert_history_for_gemini(
                    st.session_state.messages[:-1]
                )

                response = agent.process_message(
                    message=user_input,
                    history=history_for_gemini,
                    session=st.session_state.session,
                    is_voice=False,
                )

                st.session_state.session = response.session
                st.markdown(response.text)

                if response.tools_called:
                    logger.info("Tools called: %s", response.tools_called)

                # Auto-log after booking/reschedule/cancel completes
                action_tools = {"book_appointment", "reschedule_appointment", "cancel_appointment", "escalate_to_staff"}
                if action_tools & set(response.tools_called):
                    if not st.session_state.get("call_logged"):
                        log_previous_call(sheets_client, st.session_state.session, len(st.session_state.messages))
                        st.session_state.call_logged = True

        st.session_state.messages.append({"role": "assistant", "content": response.text})


if __name__ == "__main__":
    main()
