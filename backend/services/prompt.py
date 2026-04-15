"""
services/prompt.py
Loads the system prompt template and injects the live Supabase
knowledge base plus dynamic config values.
"""

from supabase import Client
from config.settings import SYSTEM_PROMPT_PATH
from services.knowledge import build_knowledge_base, get_system_config


def load_template() -> str:
    """Read the system prompt template from disk."""
    with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
        return f.read()


def build_system_prompt(db: Client) -> str:
    """
    Assemble the complete system prompt by injecting:
      - Live knowledge base data from Supabase
      - Dynamic escalation contact from system_config
    """
    template = load_template()
    config   = get_system_config(db)
    kb       = build_knowledge_base(db)

    prompt = template \
        .replace("{ESCALATION_EMAIL}", config.get("escalation_email", "admissions@egerton.ac.ke")) \
        .replace("{ESCALATION_PHONE}", config.get("escalation_phone", "")) \
        .replace("{KNOWLEDGE_BASE_CONTEXT}", kb)

    return prompt


def build_messages(history: list[dict], user_message: str) -> list[dict]:
    """
    Append the new user message to the conversation history
    and return the full messages array for the LLM.
    """
    messages = list(history)
    messages.append({"role": "user", "content": user_message})
    return messages
