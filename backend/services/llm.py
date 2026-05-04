"""
services/llm.py
═══════════════════════════════════════════════════════════════════════════════
LLM Provider Cascade:  Claude  →  Gemini  →  Rule Engine  →  Escalation


Provider order and rationale:
  1. Anthropic Claude (claude-sonnet-4-6)
       Best instruction-following. Consistent adaptive questioning.
       Reliably asks one clarifying question before answering vague queries.
       Requires ANTHROPIC_API_KEY. ~3-8 seconds per response.

  2. Google Gemini (gemini-2.5-flash)
       Free tier (15 RPM, 1M tokens/day). Good quality. Fast.
       Requires GOOGLE_API_KEY. ~2-5 seconds per response.

  3. Rule Engine (services/rule_engine.py)
       Zero network calls. Pure Python. Instant (<1 second).
       Covers 13 topic categories in English and Kiswahili.
       Works with no internet connection at all.

  4. "Still learning" escalation message
       Only reached if all three above fail simultaneously.
       In practice this should never happen.

Both APIs are optional — if a key is missing the provider is skipped
silently. The system still works correctly with only one key set.
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import logging

from supabase import Client
from config.settings import LLM_MAX_TOKENS
from services.prompt import build_system_prompt, build_messages

# Rule-based fallback — instant answers, no API required
try:
    from services.rule_engine import answer as rule_answer
except ImportError:
    rule_answer = None
    logging.getLogger(__name__).warning(
        "rule_engine not found — install services/rule_engine.py for offline fallback"
    )

logger = logging.getLogger(__name__)

# ── Model configuration ───────────────────────────────────────────────────────
CLAUDE_MODEL = os.environ.get("LLM_MODEL",      "claude-sonnet-4-6")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL",   "models/gemini-2.5-flash")

# ── Lazy-initialised API clients ──────────────────────────────────────────────
# Clients are created once on first use and reused for all subsequent requests.
# This avoids the overhead of re-authenticating on every message.
_claude_client = None
_gemini_model = None


def _get_claude():
    """Return an Anthropic client, or None if ANTHROPIC_API_KEY is not set."""
    global _claude_client
    if _claude_client is not None:
        return _claude_client

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        logger.info("Claude skipped — ANTHROPIC_API_KEY not set")
        return None

    try:
        import anthropic
        _claude_client = anthropic.Anthropic(api_key=api_key)
        logger.info(f"Claude client ready — model: {CLAUDE_MODEL}")
        return _claude_client
    except Exception as e:
        logger.warning(f"Claude client init failed: {e}")
        return None


def _get_gemini():
    """Return a Gemini GenerativeModel, or None if GOOGLE_API_KEY is not set."""
    global _gemini_model
    if _gemini_model is not None:
        return _gemini_model

    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key:
        logger.info("Gemini skipped — GOOGLE_API_KEY not set")
        return None

    try:
        import google.generativeai as genai
        from google.generativeai.types import HarmCategory, HarmBlockThreshold

        genai.configure(api_key=api_key)

        # Disable all safety filters so university content is never blocked
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
        logger.warning(f"Gemini client init failed: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# ESCALATION DETECTION
# Checks if the bot's response is admitting it cannot answer.
# Used to log unanswered questions and flag sessions as escalated.
# ══════════════════════════════════════════════════════════════════════════════

_ESCALATION_SIGNALS = [
    # English
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
    # Kiswahili
    "sina taarifa hiyo",
    "siwezi kupata",
    "wasiliana na",
    "ofisi ya udahili",
    "haipo katika mfumo wangu",
    "siwezi kujibu",
]


def is_escalation(text: str) -> bool:
    """Return True if the response text indicates EgerBot could not answer."""
    lower = text.lower()
    return any(sig in lower for sig in _ESCALATION_SIGNALS)


# ══════════════════════════════════════════════════════════════════════════════
# BILINGUAL FALLBACK MESSAGES
# Only shown when ALL providers AND the rule engine fail simultaneously.
# ══════════════════════════════════════════════════════════════════════════════

def _still_learning_message(language: str, email: str, phone: str) -> str:
    """
    Return a friendly bilingual message when no provider could answer.
    Deliberately avoids "temporarily unavailable" — instead frames it
    as EgerBot still learning, which is honest and less alarming.
    """
    if language == "sw":
        return (
            "Bado ninajifunza na sikuweza kujibu swali lako sasa hivi. "
            "EgerBot inaboreshwa kila siku!\n\n"
            f"Kwa msaada wa haraka, wasiliana na Ofisi ya Udahili:\n"
            f"📧 {email}\n"
            f"📞 {phone}\n"
            f"🌐 www.egerton.ac.ke"
        )
    return (
        "I'm still learning and couldn't answer your question right now. "
        "EgerBot is being improved every day!\n\n"
        f"For immediate help, please contact the Admissions Office:\n"
        f"📧 {email}\n"
        f"📞 {phone}\n"
        f"🌐 www.egerton.ac.ke"
    )


# ══════════════════════════════════════════════════════════════════════════════
# INDIVIDUAL PROVIDER CALLERS
# Each raises RuntimeError on failure so the cascade can move to the next.
# ══════════════════════════════════════════════════════════════════════════════

def _call_claude(system_prompt: str, messages: list) -> str:
    """
    Call Anthropic Claude. Returns response text or raises RuntimeError.
    ~3-8 seconds per response depending on answer length.
    """
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
        raise RuntimeError("Claude returned empty content")

    text = resp.content[0].text.strip()
    if not text:
        raise RuntimeError("Claude returned blank text")

    # Log token usage so we can monitor costs
    usage = getattr(resp, "usage", None)
    if usage:
        logger.info(
            f"Claude — input: {usage.input_tokens} tokens, "
            f"output: {usage.output_tokens} tokens"
        )
    return text


def _call_gemini(system_prompt: str, messages: list) -> str:
    """
    Call Google Gemini. Returns response text or raises RuntimeError.
    ~2-5 seconds per response. Free tier: 15 RPM, 1M tokens/day.
    """
    model = _get_gemini()
    if model is None:
        raise RuntimeError("Gemini not configured — GOOGLE_API_KEY missing")

    # Gemini does not support a separate system role in the same way Claude does.
    # We prepend the system prompt as the first part of the conversation.
    parts = [
        f"SYSTEM INSTRUCTIONS:\n{system_prompt}",
        "\n--- CONVERSATION ---",
    ]
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
    except Exception as e:
        raise RuntimeError(f"Gemini API call failed: {e}") from e

    if not response.candidates:
        raise RuntimeError("Gemini returned no candidates (safety filter?)")

    candidate = response.candidates[0]
    if not candidate.content or not candidate.content.parts:
        raise RuntimeError("Gemini candidate has no content parts")

    text = "".join(
        p.text for p in candidate.content.parts if hasattr(p, "text")
    ).strip()

    if not text:
        raise RuntimeError("Gemini returned empty text")

    logger.info(f"Gemini — response: {len(text)} chars")
    return text


def _call_rule_engine(user_message: str, language: str) -> str:
    """
    Call the local rule engine. Returns response text or raises RuntimeError.
    Instant — no network calls. Covers 13 topic categories bilingually.
    """
    if rule_answer is None:
        raise RuntimeError("Rule engine not available (import failed)")

    response = rule_answer(user_message, language)
    if not response:
        raise RuntimeError(
            f"Rule engine has no match for: {user_message[:60]}")

    # Add a subtle offline-mode note so users know to verify with admissions
    note_en = (
        "\n\n---\n"
        "*Note: I am currently in offline mode. "
        "For the most up-to-date information, contact admissions@egerton.ac.ke "
        "or call +254 51 221 3018.*"
    )
    note_sw = (
        "\n\n---\n"
        "*Kumbuka: Ninafanya kazi bila mtandao. "
        "Kwa taarifa za hivi karibuni, wasiliana na admissions@egerton.ac.ke "
        "au piga +254 51 221 3018.*"
    )
    return response + (note_sw if language == "sw" else note_en)


# ══════════════════════════════════════════════════════════════════════════════
# CONVERSATION HISTORY
# ══════════════════════════════════════════════════════════════════════════════

def _get_session_history(db: Client, session_id: str) -> list:
    """
    Fetch the last N messages for this session from chat_logs.
    Returns a list of {"role": "user"|"assistant", "content": str} dicts.
    """
    from config.settings import MAX_HISTORY_MESSAGES
    try:
        rows = (
            db.table("chat_logs")
            .select("user_message, bot_response")
            .eq("chat_session_id", session_id)
            .order("created_at", desc=False)
            .limit(MAX_HISTORY_MESSAGES)
            .execute()
        )
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
        logger.warning(f"Could not fetch session history ({session_id}): {e}")
        return []


def _get_escalation_contacts(db: Client) -> tuple:
    """Return (email, phone) from system_config with safe defaults."""
    try:
        rows = (
            db.table("system_config")
            .select("config_key, config_value")
            .in_("config_key", ["escalation_email", "escalation_phone"])
            .execute()
        )
        cfg = {r["config_key"]: r["config_value"] for r in (rows.data or [])}
        return (
            cfg.get("escalation_email", "admissions@egerton.ac.ke"),
            cfg.get("escalation_phone", "+254 51 221 3018"),
        )
    except Exception:
        return ("admissions@egerton.ac.ke", "+254 51 221 3018")


def _check_truncation(text: str, language: str, email: str) -> str:
    """
    Append a note if the response appears to be cut off mid-sentence.
    Only triggers for long responses that do not end with punctuation.
    """
    if text and text[-1] not in ".!?،۔।॥" and len(text) > 200:
        if language == "sw":
            return text + f"\n\n[Jibu linaweza kuwa lisilo kamili. Wasiliana {email} kwa maelezo zaidi.]"
        return text + f"\n\n[Response may be incomplete. Contact {email} for full details.]"
    return text


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def call_llm(
    db: Client,
    session_id: str,
    user_message: str,
    language: str = "en",
) -> dict:
    """
    Process a user message through the provider cascade.

    Cascade order:
        1. Claude   — best quality, consistent adaptive questioning
        2. Gemini   — free, fast, good quality
        3. Rule Engine — instant, offline, 13 topic categories
        4. Escalation  — "still learning" message with admissions contact

    Returns:
        {
            "response":  str        — bot reply, never None or empty
            "escalated": bool       — True if bot admitted it cannot answer
            "intent":    None       — reserved for future intent detection
            "error":     str|None   — error key if all providers failed
            "provider":  str        — which provider generated the response
        }
    """
    email, phone = _get_escalation_contacts(db)

    # ── Build system prompt ───────────────────────────────────────────────────
    try:
        system_prompt = build_system_prompt(db)
    except FileNotFoundError:
        logger.error("System prompt file not found — check SYSTEM_PROMPT_PATH")
        return _err(_still_learning_message(language, email, phone), "prompt_missing")
    except Exception as e:
        logger.error(f"Failed to build system prompt: {e}")
        return _err(_still_learning_message(language, email, phone), str(e))

    if not system_prompt or len(system_prompt.strip()) < 50:
        logger.error("System prompt is empty or too short")
        return _err(_still_learning_message(language, email, phone), "empty_prompt")

    # ── Build message list ────────────────────────────────────────────────────
    history = _get_session_history(db, session_id)
    messages = build_messages(history, user_message)

    # ── Cascade: Claude → Gemini ──────────────────────────────────────────────
    providers = [
        ("Claude", lambda: _call_claude(system_prompt, messages)),
        ("Gemini", lambda: _call_gemini(system_prompt, messages)),
    ]

    logger.info(f"LLM cascade starting — message: '{user_message[:60]}'")

    last_error = None
    for provider_name, caller in providers:
        try:
            logger.info(f"Trying provider: {provider_name}")
            text = caller()
            text = _check_truncation(text, language, email)

            logger.info(
                f"✓ {provider_name} responded ({len(text)} chars)"
            )
            return {
                "response":  text,
                "escalated": is_escalation(text),
                "intent":    None,
                "error":     None,
                "provider":  provider_name,
            }

        except RuntimeError as e:
            # RuntimeError = provider not configured or returned empty
            # These are expected — just move to the next provider
            logger.info(f"  {provider_name} skipped: {e}")
            last_error = str(e)

        except Exception as e:
            # Unexpected errors (network timeout, SDK bug, etc.)
            logger.warning(
                f"  {provider_name} failed: {type(e).__name__}: {e}")
            last_error = f"{type(e).__name__}: {e}"

    # ── Cascade: Rule Engine ──────────────────────────────────────────────────
    logger.warning(
        f"Both LLM providers failed — trying rule engine. Last error: {last_error}")

    try:
        rule_response = _call_rule_engine(user_message, language)
        logger.info("✓ Rule engine answered")
        return {
            "response":  rule_response,
            "escalated": False,
            "intent":    None,
            "error":     None,
            "provider":  "rule_engine",
        }
    except RuntimeError as e:
        logger.info(f"  Rule engine: no match — {e}")
    except Exception as e:
        logger.warning(f"  Rule engine error: {e}")

    # ── Cascade: Escalation message ───────────────────────────────────────────
    # All three providers failed. This should be extremely rare in practice.
    logger.error(
        f"All providers failed for message: '{user_message[:60]}'. "
        f"Last error: {last_error}"
    )
    return _err(
        _still_learning_message(language, email, phone),
        f"all_providers_failed: {last_error}",
    )


def _err(message: str, error_key: str) -> dict:
    """Return a structured error response."""
    return {
        "response":  message,
        "escalated": True,
        "intent":    None,
        "error":     error_key,
        "provider":  "none",
    }
