"""
config/settings.py
Loads all environment variables.
Every other module imports from here — never from os.environ directly.

IMPORTANT: ANTHROPIC_API_KEY is now OPTIONAL. The LLM cascade
tries Gemini → Ollama → Claude. You only need ONE provider key.
"""

import os
from dotenv import load_dotenv

load_dotenv()


# ── Supabase (REQUIRED) ──────────────────────────────────────────────────────
def _require(key: str) -> str:
    """Raise a clear error if a required env variable is missing."""
    value = os.environ.get(key)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{key}' is not set. "
            f"Check your .env file."
        )
    return value


SUPABASE_URL = _require("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = _require("SUPABASE_SERVICE_ROLE_KEY")


# ── LLM Providers — ALL OPTIONAL, cascade tries in order ────────────────────


# Google Gemini
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")

# Anthropic Claude (console.anthropic.com)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Ollama (local, no key needed — just run: ollama serve)
OLLAMA_URL = os.environ.get("OLLAMA_URL",   "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")

# Model names
LLM_MODEL = os.environ.get("LLM_MODEL",      "claude-sonnet-4-6")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL",   "gemini-1.5-flash")
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "1024"))


# ── Flask ────────────────────────────────────────────────────────────────────
FLASK_ENV = os.environ.get("FLASK_ENV",       "development")
PORT = int(os.environ.get("PORT",        5000))
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*")


# ── App behaviour ────────────────────────────────────────────────────────────
SYSTEM_PROMPT_PATH = os.environ.get(
    "SYSTEM_PROMPT_PATH",    "egerbot_system_prompt.txt")
MAX_HISTORY_MESSAGES = int(os.environ.get("MAX_HISTORY_MESSAGES",  20))
SESSION_TOKEN_EXPIRE_H = int(os.environ.get("SESSION_TOKEN_EXPIRE_H", 8))
