"""
services/llm.py
═══════════════════════════════════════════════════════════════════════════════
LLM Provider Cascade:  Google Gemini  →  Anthropic Claude

NOTE ON OLLAMA:
  Ollama runs locally on your machine. It is NOT available on Render or any
  cloud deployment — localhost:11434 does not exist on the server.
  Ollama is only tried when OLLAMA_ENABLED=true is set in your .env file
  (use this locally; never set it on Render).

Priority order:
  1. Google Gemini  (GOOGLE_API_KEY in .env / Render env vars)
  2. Anthropic      (ANTHROPIC_API_KEY in .env / Render env vars)
  [Ollama only if OLLAMA_ENABLED=true — for local dev only]

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

# Rule-based fallback — answers common questions without any LLM API
try:
    from services.rule_engine import answer as rule_answer
except ImportError:
    rule_answer = None

logger = logging.getLogger(__name__)

# ── Model names ───────────────────────────────────────────────────────────────
GEMINI_MODEL = os.environ.get("GEMINI_MODEL",    "models/gemini-1.5-flash")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL",    "llama3.2")
OLLAMA_URL = os.environ.get("OLLAMA_URL",      "http://localhost:11434")
OLLAMA_ENABLED = os.environ.get("OLLAMA_ENABLED",  "false").lower() == "true"
CLAUDE_MODEL = os.environ.get("LLM_MODEL",       "claude-sonnet-4-6")

# ── Lazy-initialised clients ─────────────────────────────────────────────────
_gemini_model = None
_claude_client = None


def _get_gemini():
    """Return a Gemini GenerativeModel, or None if not configured."""
    global _gemini_model
    if _gemini_model is not None:
        return _gemini_model

    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key:
        logger.warning("Gemini skipped — GOOGLE_API_KEY not set")
        return None

    try:
        import google.generativeai as genai
        from google.generativeai.types import HarmCategory, HarmBlockThreshold

        genai.configure(api_key=api_key)

        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT:        HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH:       HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }

        _gemini_model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            safety_settings=safety_settings,
        )
        logger.info(f"Gemini client ready — model: {GEMINI_MODEL}")
        return _gemini_model

    except Exception as e:
        logger.warning(f"Gemini init failed: {e}")
        return None


def _get_claude():
    """Return an Anthropic client, or None if not configured."""
    global _claude_client
    if _claude_client is not None:
        return _claude_client

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        logger.warning("Claude skipped — ANTHROPIC_API_KEY not set")
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
    """Return True only if Ollama is explicitly enabled AND reachable."""
    if not OLLAMA_ENABLED:
        return False          # Skip entirely in production
    try:
        # Short ping to check if Ollama is running at all
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
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
        "all_providers_failed": {
            "en": f"EgerBot is temporarily unavailable. Please contact the Admissions Office: {email} | {phone} | www.egerton.ac.ke",
            "sw": f"EgerBot haipatikani kwa muda. Tafadhali wasiliana na Ofisi ya Udahili: {email} | {phone} | www.egerton.ac.ke",
        },
        "config_error": {
            "en": f"EgerBot is not configured correctly. Please contact: {email} | {phone}",
            "sw": f"EgerBot haijasanidiwa vizuri. Tafadhali wasiliana: {email} | {phone}",
        },
        "empty_response": {
            "en": "I received an empty response. Please rephrase your question and try again.",
            "sw": "Nilipokea jibu tupu. Tafadhali unda upya swali lako na ujaribu tena.",
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
        raise RuntimeError(
            "Gemini not configured — GOOGLE_API_KEY missing or empty")

    # Combine system prompt + conversation history into a single prompt
    parts = [
        f"SYSTEM_INSTRUCTIONS:\n{system_prompt}", "\n\n--- CONVERSATION ---\n"]
    for msg in messages:
        role = "User" if msg["role"] == "user" else "EgerBot"
        parts.append(f"{role}: {msg['content']}")

    full_prompt = "\n".join(parts)

    try:
        response = model.generate_content(
            full_prompt,
            generation_config={
                "max_output_tokens": LLM_MAX_TOKENS,
                "temperature":       0.7,
            },
        )

        # Handle safety blocks or empty candidates
        if not response.candidates:
            raise RuntimeError("Gemini returned no candidates (safety block?)")

        candidate = response.candidates[0]
        if not candidate.content or not candidate.content.parts:
            raise RuntimeError("Gemini candidate has no content parts")

        text = "".join(
            p.text for p in candidate.content.parts if hasattr(p, "text")).strip()
        if not text:
            raise RuntimeError("Gemini returned empty text")

        logger.info(f"Gemini response: {len(text)} chars")
        return text

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Gemini API error: {e}") from e


def _call_ollama(system_prompt: str, messages: list) -> str:
    """Call Ollama (LOCAL ONLY). Raises if not available."""
    if not _ollama_available():
        raise RuntimeError(
            "Ollama not available — either not running locally or "
            "OLLAMA_ENABLED is false (correct for production)"
        )

    ollama_messages = [{"role": "system", "content": system_prompt}]
    for msg in messages:
        ollama_messages.append(
            {"role": msg["role"], "content": msg["content"]})

    resp = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model":    OLLAMA_MODEL,
            "messages": ollama_messages,
            "stream":   False,
            "options":  {"num_predict": LLM_MAX_TOKENS},
        },
        timeout=180,   # llama3.2 first load can take 2-3 min on slow hardware
    )
    resp.raise_for_status()
    text = resp.json().get("message", {}).get("content", "").strip()
    if not text:
        raise RuntimeError("Ollama returned empty content")
    return text


def _call_claude(system_prompt: str, messages: list) -> str:
    """Call Anthropic Claude. Returns response text or raises Exception."""
    client = _get_claude()
    if client is None:
        raise RuntimeError(
            "Claude not configured — ANTHROPIC_API_KEY missing or empty")

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

    usage = getattr(resp, "usage", None)
    if usage:
        logger.info(
            f"Claude tokens — input:{usage.input_tokens} "
            f"output:{usage.output_tokens}"
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
    Call the LLM cascade: Gemini → Claude → [Ollama if local].

    Returns:
        {
            "response":  str   — bot reply (never None)
            "escalated": bool  — True if bot could not answer
            "intent":    None  — future use
            "error":     str|None
            "provider":  str   — which provider answered
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

    # ── Provider cascade ─────────────────────────────────────────────────────
    # Gemini first (free, fast). Claude as fallback (paid, reliable).
    # Ollama only when running locally with OLLAMA_ENABLED=true.
    # Build provider list based on environment
    # Local dev (OLLAMA_ENABLED=true): Ollama first (free, private) → Gemini → Claude
    # Production (OLLAMA_ENABLED=false): Gemini first (free API) → Claude (paid fallback)
    if OLLAMA_ENABLED:
        providers = [
            ("Ollama", lambda: _call_ollama(system_prompt, messages)),
            ("Gemini", lambda: _call_gemini(system_prompt, messages)),
            ("Claude", lambda: _call_claude(system_prompt, messages)),
        ]
        logger.info("LLM cascade: Ollama → Gemini → Claude (local dev mode)")
    else:
        providers = [
            ("Gemini", lambda: _call_gemini(system_prompt, messages)),
            ("Claude", lambda: _call_claude(system_prompt, messages)),
        ]
        logger.info("LLM cascade: Gemini → Claude (production mode)")

    last_error = None
    for provider_name, caller in providers:
        try:
            logger.info(f"Trying LLM provider: {provider_name}")
            text = caller()
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
            logger.info(f"{provider_name} skipped: {e}")
            last_error = str(e)
            continue

        except Exception as e:
            logger.warning(f"{provider_name} failed: {type(e).__name__}: {e}")
            last_error = f"{type(e).__name__}: {e}"
            continue

    # ── All providers failed — try rule-based engine before giving up ───────
    logger.error(f"All LLM providers failed. Last error: {last_error}")

    if rule_answer is not None:
        try:
            rule_response = rule_answer(user_message, language)
            if rule_response:
                logger.info("Rule engine provided fallback answer")
                # Add a subtle note that this is a static answer
                note_en = "\n\n---\n*Note: I am currently operating in offline mode. For the most up-to-date information, please contact admissions@egerton.ac.ke or call +254 51 221 3018.*"
                note_sw = "\n\n---\n*Kumbuka: Ninafanya kazi bila mtandao sasa hivi. Kwa taarifa za hivi karibuni, wasiliana na admissions@egerton.ac.ke au piga +254 51 221 3018.*"
                note = note_sw if language == "sw" else note_en
                return {
                    "response":  rule_response + note,
                    "escalated": False,
                    "intent":    None,
                    "error":     None,
                    "provider":  "rule_engine",
                }
        except Exception as re_err:
            logger.warning(f"Rule engine failed: {re_err}")

    # All providers AND rule engine failed — show "still learning" message
    still_learning_en = (
        "I'm still learning and couldn't answer your question right now. "
        "EgerBot is being improved every day!\n\n"
        f"For immediate help, please contact the Admissions Office directly:\n"
        f"📧 {email}\n"
        f"📞 {phone}\n"
        f"🌐 www.egerton.ac.ke"
    )
    still_learning_sw = (
        "Bado ninajifunza na sikuweza kujibu swali lako sasa hivi. "
        "EgerBot inaboreshwa kila siku!\n\n"
        f"Kwa msaada wa haraka, wasiliana na Ofisi ya Udahili moja kwa moja:\n"
        f"📧 {email}\n"
        f"📞 {phone}\n"
        f"🌐 www.egerton.ac.ke"
    )

    return _err(
        still_learning_sw if language == "sw" else still_learning_en,
        f"all_providers_failed: {last_error}",
    )


def _check_truncation(text: str, language: str, email: str) -> str:
    """Add a note if the response looks truncated mid-sentence."""
    if text and text[-1] not in ".!?،۔।॥" and len(text) > 200:
        note = (
            f"\n\n[Response may be incomplete. For full details contact {email}]"
            if language != "sw" else
            f"\n\n[Jibu linaweza kuwa lisilo kamili. Kwa maelezo kamili wasiliana {email}]"
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
