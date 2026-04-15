"""
routes/chat.py
Public routes used by the chat widget.
No admin authentication required here.
"""

import uuid
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify

from config.supabase import get_db
from services.knowledge import get_system_config
from services.llm import call_llm
from utils.language import detect_language

chat_bp = Blueprint("chat", __name__, url_prefix="/api")


# ── Helper: log unanswered question ──────────────────────────────────────────

def _log_unanswered(db, question: str, language: str, session_id: str):
    """
    Log an unanswered / escalated question.
    Schema: unanswered_questions uses
      - status TEXT  ('open' | 'resolved')  — NOT a boolean column
      - resolved_by TEXT                    — admin who resolved it
      - times_asked INTEGER                 — frequency counter
    """
    existing = db.table("unanswered_questions") \
        .select("id, times_asked") \
        .eq("question", question) \
        .eq("status", "open") \
        .limit(1) \
        .execute()

    if existing.data:
        row = existing.data[0]
        new_count = (row.get("times_asked") or 0) + 1
        db.table("unanswered_questions") \
            .update({"times_asked": new_count}) \
            .eq("id", row["id"]) \
            .execute()
    else:
        db.table("unanswered_questions").insert({
            "question":    question,
            "language":    language,
            "session_id":  session_id,
            "status":      "open",
            "times_asked": 1,
        }).execute()


# ── Routes ────────────────────────────────────────────────────────────────────

@chat_bp.route("/greeting", methods=["GET"])
def greeting():
    db = get_db()
    cfg = get_system_config(db)
    return jsonify({
        "greeting_en": cfg.get("greeting_en", "Hello! Welcome to Egerton University. How can I help you?"),
        "greeting_sw": cfg.get("greeting_sw", "Habari! Karibu Chuo Kikuu cha Egerton. Ninawezaje kukusaidia?"),
    }), 200


@chat_bp.route("/session/start", methods=["POST"])
def start_session():
    body = request.get_json(silent=True) or {}
    user_type = body.get("user_type", "prospective")
    language = body.get("language", "en")

    db = get_db()

    # chat_sessions has BOTH:
    #   id UUID          — auto-generated PK (we return this as session_id)
    #   session_id TEXT  — unique text token we must supply (NOT NULL UNIQUE)
    session_token = str(uuid.uuid4())

    result = db.table("chat_sessions").insert({
        "session_id":     session_token,       # required TEXT column
        "user_type":      user_type,
        "language":       language,
        "started_at":     datetime.now(timezone.utc).isoformat(),
        "total_messages": 0,
        "was_resolved":   False,
        "escalated":      False,
    }).execute()

    return jsonify({"session_id": result.data[0]["id"]}), 201


@chat_bp.route("/chat", methods=["POST"])
def chat():
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "JSON body required"}), 400

    session_id = (body.get("session_id") or "").strip()
    user_message = (body.get("message") or "").strip()
    user_type = body.get("user_type", "prospective")

    if not session_id:
        return jsonify({"error": "session_id is required"}), 400
    if not user_message:
        return jsonify({"error": "message cannot be empty"}), 400

    db = get_db()

    # Check bot_active flag
    cfg = get_system_config(db)
    if cfg.get("bot_active", "true").lower() == "false":
        lang = detect_language(user_message)
        msg = cfg.get("maintenance_msg_sw") if lang == "sw" \
            else cfg.get("maintenance_msg_en", "EgerBot is under maintenance. Please try again shortly.")
        return jsonify({"response": msg, "session_id": session_id}), 200

    language = detect_language(user_message)
    result = call_llm(db, session_id, user_message, language=language)
    bot_response = result["response"]
    escalated = result["escalated"]

    if escalated:
        _log_unanswered(db, user_message, language, session_id)

    # Write to chat_logs — chat_session_id is the correct column name (not session_id)
    log_result = db.table("chat_logs").insert({
        "chat_session_id": session_id,
        "user_message":    user_message,
        "bot_response":    bot_response,
        "intent_detected": result.get("intent"),
        "user_type":       user_type,
    }).execute()

    chat_log_id = log_result.data[0]["id"] if log_result.data else None

    # Update session message counter
    session_row = db.table("chat_sessions") \
        .select("total_messages") \
        .eq("id", session_id) \
        .maybe_single() \
        .execute()

    if session_row.data:
        current_count = session_row.data.get("total_messages") or 0
        db.table("chat_sessions").update({
            "total_messages": current_count + 1,
            "escalated":      escalated,
        }).eq("id", session_id).execute()

    # Fetch quick replies
    qr_rows = db.table("quick_replies") \
        .select("label_en, label_sw, message_en, message_sw") \
        .eq("is_active", True) \
        .order("display_order") \
        .limit(3) \
        .execute()

    return jsonify({
        "response":      bot_response,
        "language":      language,
        "session_id":    session_id,
        "chat_log_id":   chat_log_id,
        "escalated":     escalated,
        "quick_replies": qr_rows.data,
    }), 200


@chat_bp.route("/feedback", methods=["POST"])
def feedback():
    body = request.get_json(silent=True) or {}
    chat_log_id = body.get("chat_log_id")
    rating = body.get("rating")
    comment = body.get("comment", "")

    if not chat_log_id:
        return jsonify({"error": "chat_log_id required"}), 400
    if not isinstance(rating, int) or not (1 <= rating <= 5):
        return jsonify({"error": "rating must be an integer between 1 and 5"}), 400

    db = get_db()
    db.table("feedback").insert({
        "chat_log_id": chat_log_id,
        "rating":      rating,
        "comment":     comment,
    }).execute()

    return jsonify({"message": "Thank you for your feedback!"}), 201


@chat_bp.route("/session/end", methods=["POST"])
def end_session():
    body = request.get_json(silent=True) or {}
    session_id = body.get("session_id")

    if not session_id:
        return jsonify({"error": "session_id required"}), 400

    db = get_db()
    db.table("chat_sessions").update({
        "ended_at":     datetime.now(timezone.utc).isoformat(),
        "was_resolved": True,
    }).eq("id", session_id).execute()

    return jsonify({"message": "Session ended"}), 200


@chat_bp.route("/session/status", methods=["GET"])
def session_status():
    session_id = request.args.get("session_id")
    if not session_id:
        return jsonify({"error": "session_id required"}), 400

    db = get_db()
    result = db.table("chat_sessions") \
        .select("id, user_type, language, started_at, total_messages, was_resolved, escalated") \
        .eq("id", session_id) \
        .maybe_single() \
        .execute()

    if not result.data:
        return jsonify({"error": "Session not found"}), 404

    return jsonify(result.data), 200


@chat_bp.route("/quick-replies", methods=["GET"])
def get_quick_replies():
    category = request.args.get("category")
    db = get_db()

    query = db.table("quick_replies") \
        .select("id, trigger_category, label_en, label_sw, message_en, message_sw, display_order") \
        .eq("is_active", True) \
        .order("display_order")

    if category:
        query = query.eq("trigger_category", category)

    result = query.execute()
    return jsonify(result.data), 200
