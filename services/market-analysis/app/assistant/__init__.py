"""Conversational assistant routes, mounted only when ASSISTANT_ENABLED is set.

The assistant reuses the existing B1~B6 endpoints (see bridge.py) and never
changes them. It answers from fact cards with fixed-form text. With APP_MODE=live
a CLOVA Studio writer (clova_client.py) words the answer, and its text is
checked against the cards before anything is published.
"""
from app.assistant.router import create_assistant_router

__all__ = ["create_assistant_router"]
