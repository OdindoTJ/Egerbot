"""
services/llm.py
═══════════════════════════════════════════════════════════════════════════════
LLM Provider Cascade:  Google Gemini  →  Ollama (local)  →  Anthropic Claude

Priority order:
  1. Google Gemini  (GOOGLE_API_KEY in .env)
  2. Ollama         (local, must be running on localhost:11434)
  3. Anthropic      (ANTHROPIC_API_KEY in .env)

If a provider fails for any reason (missing key, network error, quota) the
next provider in the list is tried automatically. A human-readable bilingual
fallback is returned only if ALL providers fail.
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import logging
import requests

from supabase import Client
from config.settings import LLM_MAX_TOKENS
from services.prompt import build_system_prompt, build_messages

logger = logging.getLogger(__name__)

# ── Model names ───────────────────────────────────────────────────────────────
GEMINI_MODEL = os.environ.get("GEMINI_MODEL",  "gemini-1.5-flash")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL",  "llama3.2")
OLLAMA_URL = os.environ.get("OLLAMA_URL",    "http://localhost:11434")
CLAUDE_MODEL = os.environ.get("LLM_MODEL",     "claude-sonnet-4-6")

# ── Lazy-initialised clients ─────────────────────────────────────────────────
_gemini_model = None
_claude_client = None


def _get_gemini():
    """Return a Gemini GenerativeModel with relaxed safety settings."""
    global _gemini_model
    if _gemini_model is not None:
        return _gemini_model

    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key:
        logger.error("GOOGLE_API_KEY not found in environment variables")
        return None

    try:
        import google.generativeai as genai
        from google.generativeai.types import HarmCategory, HarmBlockThreshold

        genai.configure(api_key=api_key)

        models_to_try = [
            "models/gemini-2.5-flash",
            "models/gemini-2.0-flash",
            "models/gemini-flash-latest",
            "models/gemini-2.5-flash-lite",
            "models/gemini-2.0-flash-lite",
        ]

        # Relaxed safety settings to prevent empty responses on the free tier
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }

        # Initialize the model with these settings
        _gemini_model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            safety_settings=safety_settings
        )

        logger.info(
            f"Gemini client ready — model: {GEMINI_MODEL} (Safety: relaxed)")
        return _gemini_model

    except Exception as e:
        logger.warning(f"Gemini init failed: {e}")
        return None


def _get_claude():
    """Return an Anthropic client, or None if not available."""
    global _claude_client
    if _claude_client is not None:
        return _claude_client
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import anthropic
        _claude_client = anthropic.Anthropic(api_key=api_key)
        logger.info("Anthropic Claude client ready")
        return _claude_client
    except Exception as e:
        logger.warning(f"Claude init failed: {e}")
        return None


def _ollama_available() -> bool:
    """Return True if the Ollama server is reachable."""
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# ESCALATION DETECTION
# ══════════════════════════════════════════════════════════════════════════════

_ESCALATION_SIGNALS = [
    "i don't have that specific information",
    "i don't have that detail",
    "i cannot find",
    "please contact",
    "contact the admissions",
    "contact admissions",
    "i am unable to",
    "i'm unable to",
    "not in my knowledge base",
    "cannot answer that",
    "sina taarifa hiyo",
    "siwezi kupata",
    "wasiliana na",
    "ofisi ya udahili",
    "haipo katika mfumo wangu",
    "siwezi kujibu",
]


def is_escalation(text: str) -> bool:
    lower = text.lower()
    return any(sig in lower for sig in _ESCALATION_SIGNALS)


# ══════════════════════════════════════════════════════════════════════════════
# BILINGUAL FALLBACK MESSAGES
# ══════════════════════════════════════════════════════════════════════════════

def _fallback(language: str, error_type: str,
              email: str = "admissions@egerton.ac.ke",
              phone: str = "+254 51 221 3018") -> str:
    msgs = {
        "auth_error": {
            "en": f"I'm unable to connect to my AI service right now. Please contact us directly: {email} | {phone} | www.egerton.ac.ke",
            "sw": f"Siwezi kuunganisha na huduma yangu ya AI sasa hivi. Tafadhali wasiliana nasi moja kwa moja: {email} | {phone} | www.egerton.ac.ke",
        },
        "quota_exceeded": {
            "en": f"EgerBot has reached its usage limit for now. For immediate help: {email} | {phone} | www.egerton.ac.ke",
            "sw": f"EgerBot imefika kikomo chake cha matumizi. Kwa msaada wa haraka: {email} | {phone} | www.egerton.ac.ke",
        },
        "rate_limit": {
            "en": "I'm receiving too many requests right now. Please wait a few seconds and try again.",
            "sw": "Ninapokea maombi mengi sana sasa hivi. Tafadhali subiri sekunde chache na ujaribu tena.",
        },
        "all_providers_failed": {
            "en": f"EgerBot is temporarily unavailable. Please contact the Admissions Office directly: {email} | {phone} | www.egerton.ac.ke",
            "sw": f"EgerBot haipatikani kwa muda. Tafadhali wasiliana na Ofisi ya Udahili moja kwa moja: {email} | {phone} | www.egerton.ac.ke",
        },
        "connection_error": {
            "en": f"I'm having trouble connecting right now. Please try again, or contact: {email} | {phone}",
            "sw": f"Nina tatizo la kuunganisha sasa hivi. Tafadhali jaribu tena, au wasiliana: {email} | {phone}",
        },
        "timeout": {
            "en": f"My response is taking too long. Please try again or contact: {email} | {phone}",
            "sw": f"Jibu langu linachukua muda mrefu. Tafadhali jaribu tena au wasiliana: {email} | {phone}",
        },
        "empty_response": {
            "en": "I received an empty response. Please rephrase your question and try again.",
            "sw": "Nilipokea jibu tupu. Tafadhali unda upya swali lako na ujaribu tena.",
        },
        "config_error": {
            "en": f"EgerBot is not configured correctly at the moment. Please contact: {email} | {phone}",
            "sw": f"EgerBot haijasanidiwa vizuri kwa sasa hivi. Tafadhali wasiliana: {email} | {phone}",
        },
        "unexpected": {
            "en": f"Something went wrong. Please try again, or contact: {email} | {phone}",
            "sw": f"Kuna tatizo fulani. Tafadhali jaribu tena, au wasiliana: {email} | {phone}",
        },
    }
    lang = "sw" if language == "sw" else "en"
    return msgs.get(error_type, msgs["unexpected"])[lang]


# ══════════════════════════════════════════════════════════════════════════════
# INDIVIDUAL PROVIDER CALLERS
# ══════════════════════════════════════════════════════════════════════════════

def _call_gemini(system_prompt: str, messages: list) -> str:
    """Call Google Gemini. Returns response text or raises Exception."""
    model = _get_gemini()
    if model is None:
        raise RuntimeError("Gemini not configured — GOOGLE_API_KEY missing")

    # Build a single prompt string: system + conversation
    # Using a clear structure helps the model distinguish instructions from history
    parts = [f"SYSTEM_INSTRUCTIONS:\n{system_prompt}",
             "\n\n--- CONVERSATION HISTORY ---\n"]
    for msg in messages:
        # Use 'user' and 'model' as these are the native Gemini roles
        role = "User" if msg["role"] == "user" else "EgerBot"
        parts.append(f"{role}: {msg['content']}")

    full_prompt = "\n".join(parts)

    try:
        # We call generate_content. Note: safety_settings are already in _get_gemini
        response = model.generate_content(
            full_prompt,
            generation_config={"max_output_tokens": LLM_MAX_TOKENS},
        )

        # CRITICAL: Check if the response was blocked before accessing .text
        if not response.candidates:
            # If blocked by safety filters, candidates list will be empty
            logger.warning("Gemini blocked the response (Safety/Other).")
            raise RuntimeError(
                "Gemini blocked the response due to safety filters.")

        # Access text safely
        text = response.text.strip()

        if not text:
            raise RuntimeError("Gemini returned empty text")

        return text

    except ValueError as e:
        # This usually happens if response.text is accessed on a blocked response
        logger.error(f"Gemini Safety Block or Parse Error: {e}")
        raise RuntimeError(f"Gemini could not generate text: {e}")
    except Exception as e:
        logger.error(f"Gemini API call failed: {e}")
        raise


def _call_ollama(system_prompt: str, messages: list) -> str:
    """Call local Ollama. Returns response text or raises Exception."""
    if not _ollama_available():
        raise RuntimeError(f"Ollama not reachable at http://localhost:11434")

    # Build messages array for Ollama's /api/chat endpoint
    ollama_messages = [{"role": "system", "content": system_prompt}]
    for msg in messages:
        ollama_messages.append(
            {"role": msg["role"], "content": msg["content"]})

    resp = requests.post(
        "http://localhost:11434/api/chat",  # Hardcode correct URL
        json={
            "model":    OLLAMA_MODEL,
            "messages": ollama_messages,
            "stream":   False,
            "options":  {"num_predict": LLM_MAX_TOKENS},
        },
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data.get("message", {}).get("content", "").strip()
    if not text:
        raise RuntimeError("Ollama returned empty content")
    return text


def _call_claude(system_prompt: str, messages: list) -> str:
    """Call Anthropic Claude. Returns response text or raises Exception."""
    import anthropic
    client = _get_claude()
    if client is None:
        raise RuntimeError("Claude not configured — ANTHROPIC_API_KEY missing")

    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=LLM_MAX_TOKENS,
        system=system_prompt,
        messages=messages,
    )

    if not resp.content:
        raise RuntimeError("Claude returned empty content list")
    text = resp.content[0].text.strip()
    if not text:
        raise RuntimeError("Claude returned blank text")

    # Log token usage
    usage = getattr(resp, "usage", None)
    if usage:
        logger.info(
            f"Claude tokens — input:{usage.input_tokens} "
            f"output:{usage.output_tokens} "
            f"total:{usage.input_tokens + usage.output_tokens}"
        )
    return text


# ══════════════════════════════════════════════════════════════════════════════
# CONVERSATION HISTORY
# ══════════════════════════════════════════════════════════════════════════════

def get_session_history(db: Client, session_id: str) -> list:
    """Fetch recent message history for this session."""
    from config.settings import MAX_HISTORY_MESSAGES
    try:
        rows = db.table("chat_logs") \
            .select("user_message, bot_response") \
            .eq("chat_session_id", session_id) \
            .order("created_at", desc=False) \
            .limit(MAX_HISTORY_MESSAGES) \
            .execute()
        history = []
        for row in rows.data:
            if row.get("user_message"):
                history.append(
                    {"role": "user",      "content": row["user_message"]})
            if row.get("bot_response"):
                history.append(
                    {"role": "assistant", "content": row["bot_response"]})
        return history
    except Exception as e:
        logger.warning(
            f"Could not fetch session history for {session_id}: {e}")
        return []


def _get_contacts(db: Client) -> tuple:
    """Return (email, phone) from system_config with safe defaults."""
    try:
        rows = db.table("system_config") \
            .select("config_key, config_value") \
            .in_("config_key", ["escalation_email", "escalation_phone"]) \
            .execute()
        cfg = {r["config_key"]: r["config_value"] for r in (rows.data or [])}
        return (
            cfg.get("escalation_email", "admissions@egerton.ac.ke"),
            cfg.get("escalation_phone", "+254 51 221 3018"),
        )
    except Exception:
        return ("admissions@egerton.ac.ke", "+254 51 221 3018")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def call_llm(db: Client, session_id: str, user_message: str,
             language: str = "en") -> dict:
    """
    Call the LLM cascade: Gemini → Ollama → Claude.

    Returns:
        {
            "response":   str   — bot reply (never None)
            "escalated":  bool  — True if bot could not answer
            "intent":     None  — future use
            "error":      str|None
            "provider":   str   — which provider answered
        }
    """
    email, phone = _get_contacts(db)

    # ── Build system prompt ──────────────────────────────────────────────────
    try:
        system_prompt = build_system_prompt(db)
    except FileNotFoundError:
        logger.error(
            "System prompt file not found — check SYSTEM_PROMPT_PATH in .env")
        return _err(_fallback(language, "config_error", email, phone), "prompt_missing")
    except Exception as e:
        logger.error(f"Failed to build system prompt: {e}")
        return _err(_fallback(language, "config_error", email, phone), str(e))

    if not system_prompt or len(system_prompt.strip()) < 50:
        logger.error("System prompt is empty or too short")
        return _err(_fallback(language, "config_error", email, phone), "empty_prompt")

    # ── Build messages ───────────────────────────────────────────────────────
    history = get_session_history(db, session_id)
    messages = build_messages(history, user_message)

    # ── Try each provider in order ───────────────────────────────────────────
    providers = [
        ("Gemini", lambda: _call_gemini(system_prompt, messages)),
        ("Ollama", lambda: _call_ollama(system_prompt, messages)),
        ("Claude", lambda: _call_claude(system_prompt, messages)),
    ]

    last_error = None
    for provider_name, caller in providers:
        try:
            logger.info(f"Trying LLM provider: {provider_name}")
            text = caller()

            # Handle max-token truncation
            text = _check_truncation(text, language, email)

            logger.info(f"Response from {provider_name} ({len(text)} chars)")
            return {
                "response":  text,
                "escalated": is_escalation(text),
                "intent":    None,
                "error":     None,
                "provider":  provider_name,
            }

        except RuntimeError as e:
            # Configuration / availability issue — skip silently, try next
            logger.info(f"{provider_name} skipped: {e}")
            last_error = str(e)
            continue

        except Exception as e:
            # Actual API error — log it, try next
            logger.warning(f"{provider_name} failed: {type(e).__name__}: {e}")
            last_error = f"{type(e).__name__}: {e}"
            continue

    # ── All providers failed ─────────────────────────────────────────────────
    logger.error(f"All LLM providers failed. Last error: {last_error}")
    return _err(
        _fallback(language, "all_providers_failed", email, phone),
        f"all_providers_failed: {last_error}",
    )


def _check_truncation(text: str, language: str, email: str) -> str:
    """Add a note if the response looks truncated."""
    # Heuristic: ends mid-sentence without punctuation
    if text and not text[-1] in ".!?،۔।॥":
        # Only add note if text is already substantial (>200 chars)
        if len(text) > 200:
            note = (
                f"\n\n[Response may be incomplete. For full details, contact {email}]"
                if language != "sw" else
                f"\n\n[Jibu linaweza kuwa lisilo kamili. Kwa maelezo kamili, wasiliana {email}]"
            )
            return text + note
    return text


def _err(message: str, error_key: str) -> dict:
    return {
        "response":  message,
        "escalated": True,
        "intent":    None,
        "error":     error_key,
        "provider":  "none",
    }