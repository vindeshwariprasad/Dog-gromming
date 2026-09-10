"""
Vapi assistant configuration.

Use this to create/update the Vapi assistant via the Vapi API,
or configure it manually in the Vapi dashboard.

The assistant should be configured as a "custom-llm" provider,
pointing to your server's /chat/completions endpoint.
"""

VAPI_ASSISTANT_CONFIG = {
    "name": "Maple Street Dog Grooming Receptionist",
    "model": {
        "provider": "custom-llm",
        "url": "<YOUR_NGROK_URL>",  # e.g., "https://abc123.ngrok.io"
        "model": "maple-street-receptionist",
    },
    "voice": {
        "provider": "11labs",
        "voiceId": "21m00Tcm4TlvDq8ikWAM",  # "Rachel" - friendly female voice
        "stability": 0.5,
        "similarityBoost": 0.75,
    },
    "firstMessage": "Hi! Welcome to Maple Street Dog Grooming. How can I help you today?",
    "transcriber": {
        "provider": "deepgram",
        "model": "nova-2",
        "language": "en",
    },
    "silenceTimeoutSeconds": 30,
    "maxDurationSeconds": 600,
    "endCallMessage": "Thanks for calling Maple Street Dog Grooming! Have a great day.",
}
