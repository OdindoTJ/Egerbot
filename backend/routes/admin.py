"""
routes/admin.py
All admin API routes — protected by JWT auth.
Fixes applied:
  - analytics: .eq("status","open") not .eq("resolved",False)
  - chat_logs select: chat_session_id only (no session_id column)
  - unanswered_questions: status TEXT column, not boolean resolved
  - convert_to_faq: updates status="resolved" not resolved=True
  - login token stored in localStorage (persists page refresh)
"""

import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from functools import wraps

import bcrypt
import jwt
from flask import Blueprint, g, jsonify, request

from config.settings import SESSION_TOKEN_EXPIRE_H
from config.supabase import get_db

logger = logging.getLogger(__name__)
admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")
JWT_SECRET = "egerbot-admin-secret-change-in-production"


# ══════════════════════════════════════════════════════════════════════════════
# AUTH HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _make_token(admin_id: str) -> str:
    payload = {
        "admin_id": admin_id,
        "exp":      datetime.now(timezone.utc) + timedelta(hours=SESSION_TOKEN_EXPIRE_H),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _verify_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "Unauthorised"}), 401
        token = auth[7:]
        payload = _verify_token(token)
        if not payload:
            return jsonify({"error": "Token invalid or expired"}), 401
        g.admin_id = payload["admin_id"]
        return f(*args, **kwargs)
    return decorated


def get_admin_email(admin_id: str) -> str:
    """Return admin email for audit log entries."""
    try:
        db = get_db()
        result = db.table("admin_users").select("email").eq(
            "id", admin_id).maybe_single().execute()
        return result.data["email"] if result.data else "unknown"
    except Exception:
        return "unknown"


def _audit(db, table: str, record_id: str, change_type: str, notes: str = ""):
    """Write an entry to the updates_log audit table."""
    try:
        db.table("updates_log").insert({
            "table_name":  table,
            "record_id":   str(record_id),
            "change_type": change_type,
            "changed_by":  get_admin_email(g.admin_id),
            "notes":       notes,
            "updated_at":  datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        logger.warning(f"Audit log failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# AUTH ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/login", methods=["POST"])
def login():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = (body.get("password") or "").strip()

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    db = get_db()
    result = db.table("admin_users") \
        .select("id, name, email, password_hash, role, is_active") \
        .eq("email", email) \
        .maybe_single() \
        .execute()

    if not result.data:
        return jsonify({"error": "Invalid email or password"}), 401

    admin = result.data
    if not admin.get("is_active"):
        return jsonify({"error": "Account is disabled"}), 403

    pw_hash = admin.get("password_hash", "")
    try:
        if not bcrypt.checkpw(password.encode(), pw_hash.encode()):
            return jsonify({"error": "Invalid email or password"}), 401
    except Exception:
        return jsonify({"error": "Invalid email or password"}), 401

    token = _make_token(admin["id"])

    # Update last login
    db.table("admin_users").update({
        "last_login": datetime.now(timezone.utc).isoformat()
    }).eq("id", admin["id"]).execute()

    return jsonify({
        "token": token,
        "admin": {
            "id":    admin["id"],
            "name":  admin["name"],
            "email": admin["email"],
            "role":  admin["role"],
        }
    }), 200


@admin_bp.route("/logout", methods=["POST"])
@require_admin
def logout():
    return jsonify({"message": "Logged out"}), 200


@admin_bp.route("/me", methods=["GET"])
@require_admin
def me():
    db = get_db()
    result = db.table("admin_users") \
        .select("id, name, email, role, last_login") \
        .eq("id", g.admin_id) \
        .maybe_single() \
        .execute()
    if not result.data:
        return jsonify({"error": "Admin not found"}), 404
    return jsonify(result.data), 200


# ══════════════════════════════════════════════════════════════════════════════
# ANALYTICS — DASHBOARD STAT CARDS
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/analytics", methods=["GET"])
@require_admin
def get_analytics():
    """
    Return aggregate counts for the dashboard overview stat cards.
    KEY FIX: unanswered_questions uses status='open' (TEXT), NOT resolved=False (BOOLEAN)
    """
    db = get_db()

    # Total chat sessions
    sessions = db.table("chat_sessions").select("id", count="exact").execute()

    # Total messages logged
    messages = db.table("chat_logs").select("id", count="exact").execute()

    # Unanswered / open questions — status TEXT column, NOT boolean resolved
    unresolved = db.table("unanswered_questions") \
        .select("id", count="exact") \
        .eq("status", "open") \
        .execute()

    # Escalated sessions
    escalated = db.table("chat_sessions") \
        .select("id", count="exact") \
        .eq("escalated", True) \
        .execute()

    # Average feedback rating
    feedback = db.table("feedback").select("rating").execute()
    ratings = [r["rating"] for r in (feedback.data or []) if r.get("rating")]
    avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else None

    # Total FAQ entries
    faqs = db.table("faqs").select("id", count="exact").execute()

    return jsonify({
        "total_sessions":       sessions.count or 0,
        "total_messages":       messages.count or 0,
        "unresolved_questions": unresolved.count or 0,
        "escalated_sessions":   escalated.count or 0,
        "average_rating":       avg_rating or 0,
        "total_feedback":       len(ratings),
        "total_faqs":           faqs.count or 0,
    }), 200


@admin_bp.route("/analytics/daily", methods=["GET"])
@require_admin
def daily_analytics():
    """Daily session counts for the last 14 days (chart data)."""
    db = get_db()

    since = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    rows = db.table("chat_sessions") \
        .select("started_at") \
        .gte("started_at", since) \
        .execute()

    # Count by date
    counts: dict[str, int] = {}
    for row in (rows.data or []):
        ts = row.get("started_at", "")[:10]   # YYYY-MM-DD
        counts[ts] = counts.get(ts, 0) + 1

    # Fill in missing dates with 0
    result = []
    for i in range(13, -1, -1):
        d = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
        result.append({"date": d, "sessions": counts.get(d, 0)})

    return jsonify(result), 200


@admin_bp.route("/analytics/popular-questions", methods=["GET"])
@require_admin
def popular_questions():
    """Top 10 most asked questions from unanswered_questions by times_asked."""
    db = get_db()
    rows = db.table("unanswered_questions") \
        .select("question, times_asked, language") \
        .order("times_asked", desc=True) \
        .limit(10) \
        .execute()
    return jsonify(rows.data or []), 200


# ══════════════════════════════════════════════════════════════════════════════
# CHAT LOGS
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/logs", methods=["GET"])
@require_admin
def get_logs():
    """
    Paginated chat log listing.
    KEY FIX: select chat_session_id only — no 'session_id' column in chat_logs.
    """
    page = int(request.args.get("page",  1))
    per_page = int(request.args.get("limit", 20))
    search = request.args.get("search",    "").strip()
    user_type = request.args.get("user_type", "").strip()

    offset = (page - 1) * per_page
    db = get_db()

    # chat_logs columns: id, chat_session_id, user_message, bot_response,
    #                    intent_detected, user_type, created_at
    query = db.table("chat_logs") \
        .select("id, chat_session_id, user_message, bot_response, user_type, created_at") \
        .order("created_at", desc=True) \
        .range(offset, offset + per_page - 1)

    if user_type:
        query = query.eq("user_type", user_type)

    result = query.execute()
    return jsonify(result.data or []), 200


@admin_bp.route("/logs/export", methods=["GET"])
@require_admin
def export_logs():
    """Download all chat logs as CSV."""
    db = get_db()
    rows = db.table("chat_logs") \
        .select("id, chat_session_id, user_message, bot_response, user_type, created_at") \
        .order("created_at", desc=True) \
        .execute()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "session_id", "user_message",
                    "bot_response", "user_type", "created_at"])
    for row in (rows.data or []):
        writer.writerow([
            row.get("id"),
            row.get("chat_session_id"),
            row.get("user_message"),
            row.get("bot_response"),
            row.get("user_type"),
            row.get("created_at"),
        ])

    from flask import Response
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=egerbot_chat_logs.csv"},
    )


@admin_bp.route("/sessions", methods=["GET"])
@require_admin
def list_sessions():
    page = int(request.args.get("page",  1))
    per_page = int(request.args.get("limit", 20))
    offset = (page - 1) * per_page
    db = get_db()

    result = db.table("chat_sessions") \
        .select("id, user_type, language, started_at, ended_at, total_messages, was_resolved, escalated") \
        .order("started_at", desc=True) \
        .range(offset, offset + per_page - 1) \
        .execute()
    return jsonify(result.data or []), 200


@admin_bp.route("/sessions/<session_id>/messages", methods=["GET"])
@require_admin
def session_messages(session_id):
    db = get_db()
    result = db.table("chat_logs") \
        .select("id, user_message, bot_response, user_type, created_at") \
        .eq("chat_session_id", session_id) \
        .order("created_at") \
        .execute()
    return jsonify(result.data or []), 200


# ══════════════════════════════════════════════════════════════════════════════
# UNANSWERED QUESTIONS
# KEY FIX: entire section uses status TEXT ('open'/'resolved'), not boolean columns
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/unanswered", methods=["GET"])
@require_admin
def list_unanswered():
    """
    List unanswered questions sorted by frequency.
    status parameter: 'all' | 'open' | 'resolved'
    Schema: status TEXT ('open'|'resolved'), resolved_by TEXT, times_asked INT
    """
    status = request.args.get("status", "open")   # default: show open
    db = get_db()

    query = db.table("unanswered_questions") \
        .select("id, question, language, times_asked, status, resolved_by, notes, created_at") \
        .order("times_asked", desc=True)

    # Filter by status using the TEXT column (not a boolean)
    if status == "open":
        query = query.eq("status", "open")
    elif status == "resolved":
        query = query.eq("status", "resolved")
    # else "all" — no filter

    result = query.execute()
    return jsonify(result.data or []), 200


@admin_bp.route("/unanswered/<question_id>", methods=["PATCH"])
@require_admin
def update_unanswered(question_id):
    """
    Update an unanswered question record.
    Allowed fields: status, resolved_by, notes, times_asked
    NOT: resolved (boolean), reviewed (boolean) — those columns don't exist.
    """
    body = request.get_json(silent=True) or {}
    allowed = {"status", "resolved_by", "notes", "times_asked"}
    update = {k: v for k, v in body.items() if k in allowed}

    if not update:
        return jsonify({"error": "No valid fields provided"}), 400

    db = get_db()
    db.table("unanswered_questions").update(
        update).eq("id", question_id).execute()
    return jsonify({"message": "Updated"}), 200


@admin_bp.route("/unanswered/<question_id>/convert-faq", methods=["POST"])
@require_admin
def convert_to_faq(question_id):
    """One-click: create a FAQ from an unanswered question and mark it resolved."""
    body = request.get_json(silent=True) or {}

    if not body.get("answer_en"):
        return jsonify({"error": "answer_en is required"}), 400
    if not body.get("question_en") and not body.get("question"):
        return jsonify({"error": "question_en is required"}), 400

    db = get_db()

    # Get original question text if not supplied
    question_text = body.get("question_en") or body.get("question")
    if not question_text:
        orig = db.table("unanswered_questions") \
            .select("question") \
            .eq("id", question_id) \
            .maybe_single() \
            .execute()
        if orig.data:
            question_text = orig.data["question"]

    # Create FAQ entry
    faq = db.table("faqs").insert({
        "question_en":  question_text,
        "question_sw":  body.get("question_sw"),
        "answer_en":    body["answer_en"],
        "answer_sw":    body.get("answer_sw"),
        "category":     body.get("category", "general"),
        "tags":         body.get("tags", []),
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }).execute()

    # Mark original question as resolved — status TEXT column (not boolean resolved)
    db.table("unanswered_questions").update({
        "status":      "resolved",
        "resolved_by": get_admin_email(g.admin_id),
        "notes":       f"Converted to FAQ: {faq.data[0]['id']}",
    }).eq("id", question_id).execute()

    _audit(db, "faqs", faq.data[0]["id"], "insert",
           f"Converted from unanswered: {question_id}")
    return jsonify({"message": "Converted to FAQ", "faq": faq.data[0]}), 201


@admin_bp.route("/unanswered/<question_id>", methods=["DELETE"])
@require_admin
def delete_unanswered(question_id):
    db = get_db()
    db.table("unanswered_questions").delete().eq("id", question_id).execute()
    return jsonify({"message": "Deleted"}), 200


# ══════════════════════════════════════════════════════════════════════════════
# FAQs
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/faqs", methods=["GET"])
@require_admin
def list_faqs():
    category = request.args.get("category")
    search = request.args.get("search", "").strip()
    db = get_db()
    query = db.table("faqs").select("*").order("category")

    if category:
        query = query.eq("category", category)

    result = query.execute()
    data = result.data or []

    if search:
        search_lower = search.lower()
        data = [r for r in data
                if search_lower in (r.get("question_en") or "").lower()
                or search_lower in (r.get("answer_en") or "").lower()]

    return jsonify(data), 200


@admin_bp.route("/faqs/<faq_id>", methods=["GET"])
@require_admin
def get_faq(faq_id):
    db = get_db()
    result = db.table("faqs").select(
        "*").eq("id", faq_id).maybe_single().execute()
    if not result.data:
        return jsonify({"error": "FAQ not found"}), 404
    return jsonify(result.data), 200


@admin_bp.route("/faqs", methods=["POST"])
@require_admin
def create_faq():
    body = request.get_json(silent=True) or {}
    if not body.get("question_en") or not body.get("answer_en"):
        return jsonify({"error": "question_en and answer_en are required"}), 400

    db = get_db()
    row = db.table("faqs").insert({
        "question_en":  body["question_en"],
        "question_sw":  body.get("question_sw"),
        "answer_en":    body["answer_en"],
        "answer_sw":    body.get("answer_sw"),
        "category":     body.get("category", "general"),
        "tags":         body.get("tags", []),
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }).execute()

    _audit(db, "faqs", row.data[0]["id"], "insert")
    return jsonify(row.data[0]), 201


@admin_bp.route("/faqs/<faq_id>", methods=["PATCH"])
@require_admin
def update_faq(faq_id):
    body = request.get_json(silent=True) or {}
    allowed = {"question_en", "question_sw",
               "answer_en", "answer_sw", "category", "tags"}
    update = {k: v for k, v in body.items() if k in allowed}
    if not update:
        return jsonify({"error": "No valid fields"}), 400

    update["last_updated"] = datetime.now(timezone.utc).isoformat()
    db = get_db()
    db.table("faqs").update(update).eq("id", faq_id).execute()
    _audit(db, "faqs", faq_id, "update")
    return jsonify({"message": "Updated"}), 200


@admin_bp.route("/faqs/<faq_id>", methods=["DELETE"])
@require_admin
def delete_faq(faq_id):
    db = get_db()
    db.table("faqs").delete().eq("id", faq_id).execute()
    _audit(db, "faqs", faq_id, "delete")
    return jsonify({"message": "Deleted"}), 200


@admin_bp.route("/faqs/export", methods=["GET"])
@require_admin
def export_faqs():
    db = get_db()
    rows = db.table("faqs").select("*").execute()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "question_en", "question_sw",
                    "answer_en", "answer_sw", "category", "tags"])
    for r in (rows.data or []):
        writer.writerow([
            r.get("id"), r.get("question_en"), r.get("question_sw"),
            r.get("answer_en"), r.get("answer_sw"), r.get("category"),
            ",".join(r.get("tags") or []),
        ])

    from flask import Response
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=egerbot_faqs.csv"},
    )


# ══════════════════════════════════════════════════════════════════════════════
# PROGRAMMES
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/programs", methods=["GET"])
@require_admin
def list_programs():
    faculty = request.args.get("faculty")
    level = request.args.get("level")
    active = request.args.get("active", "true")
    db = get_db()
    query = db.table("programs") \
        .select("id, code, name_en, name_sw, faculty, department, level, duration, "
                "kcse_min_grade, active, career_prospects_en") \
        .order("faculty")

    if faculty:
        query = query.eq("faculty", faculty)
    if level:
        query = query.eq("level", level)
    if active == "true":
        query = query.eq("active", True)
    elif active == "false":
        query = query.eq("active", False)

    result = query.execute()
    return jsonify(result.data or []), 200


@admin_bp.route("/programs/<program_id>", methods=["GET"])
@require_admin
def get_program(program_id):
    db = get_db()
    result = db.table("programs").select(
        "*").eq("id", program_id).maybe_single().execute()
    if not result.data:
        return jsonify({"error": "Programme not found"}), 404
    return jsonify(result.data), 200


@admin_bp.route("/programs", methods=["POST"])
@require_admin
def create_program():
    body = request.get_json(silent=True) or {}
    if not body.get("name_en") or not body.get("faculty"):
        return jsonify({"error": "name_en and faculty are required"}), 400

    db = get_db()
    row = db.table("programs").insert({
        "code":              body.get("code"),
        "name_en":           body["name_en"],
        "name_sw":           body.get("name_sw"),
        "faculty":           body["faculty"],
        "department":        body.get("department"),
        "level":             body.get("level"),
        "duration":          body.get("duration"),
        "kcse_min_grade":    body.get("kcse_min_grade"),
        "cluster_subjects":  body.get("cluster_subjects"),
        "career_prospects_en": body.get("career_prospects_en"),
        "active":            body.get("active", True),
    }).execute()

    _audit(db, "programs", row.data[0]["id"], "insert")
    return jsonify(row.data[0]), 201


@admin_bp.route("/programs/<program_id>", methods=["PATCH"])
@require_admin
def update_program(program_id):
    body = request.get_json(silent=True) or {}
    allowed = {"name_en", "name_sw", "faculty", "department", "level",
               "duration", "kcse_min_grade", "cluster_subjects",
               "career_prospects_en", "active", "code"}
    update = {k: v for k, v in body.items() if k in allowed}
    if not update:
        return jsonify({"error": "No valid fields"}), 400

    db = get_db()
    db.table("programs").update(update).eq("id", program_id).execute()
    _audit(db, "programs", program_id, "update")
    return jsonify({"message": "Updated"}), 200


@admin_bp.route("/programs/<program_id>", methods=["DELETE"])
@require_admin
def delete_program(program_id):
    db = get_db()
    # Soft delete — set active=False
    db.table("programs").update({"active": False}).eq(
        "id", program_id).execute()
    _audit(db, "programs", program_id, "delete", "Soft deleted (active=False)")
    return jsonify({"message": "Programme deactivated"}), 200


# ══════════════════════════════════════════════════════════════════════════════
# QUICK REPLIES
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/quick-replies", methods=["GET"])
@require_admin
def list_quick_replies():
    db = get_db()
    result = db.table("quick_replies") \
        .select("*") \
        .order("display_order") \
        .execute()
    return jsonify(result.data or []), 200


@admin_bp.route("/quick-replies", methods=["POST"])
@require_admin
def create_quick_reply():
    body = request.get_json(silent=True) or {}
    if not body.get("label_en") or not body.get("message_en"):
        return jsonify({"error": "label_en and message_en are required"}), 400

    db = get_db()
    row = db.table("quick_replies").insert({
        "trigger_category": body.get("trigger_category", "general"),
        "label_en":         body["label_en"],
        "label_sw":         body.get("label_sw"),
        "message_en":       body["message_en"],
        "message_sw":       body.get("message_sw"),
        "display_order":    body.get("display_order", 99),
        "is_active":        body.get("is_active", True),
    }).execute()

    _audit(db, "quick_replies", row.data[0]["id"], "insert")
    return jsonify(row.data[0]), 201


@admin_bp.route("/quick-replies/<reply_id>", methods=["PATCH"])
@require_admin
def update_quick_reply(reply_id):
    body = request.get_json(silent=True) or {}
    allowed = {"trigger_category", "label_en", "label_sw",
               "message_en", "message_sw", "display_order", "is_active"}
    update = {k: v for k, v in body.items() if k in allowed}
    if not update:
        return jsonify({"error": "No valid fields"}), 400

    db = get_db()
    db.table("quick_replies").update(update).eq("id", reply_id).execute()
    _audit(db, "quick_replies", reply_id, "update")
    return jsonify({"message": "Updated"}), 200


@admin_bp.route("/quick-replies/<reply_id>", methods=["DELETE"])
@require_admin
def delete_quick_reply(reply_id):
    db = get_db()
    db.table("quick_replies").delete().eq("id", reply_id).execute()
    _audit(db, "quick_replies", reply_id, "delete")
    return jsonify({"message": "Deleted"}), 200


# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM CONFIG
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/config", methods=["GET"])
@require_admin
def get_config():
    db = get_db()
    result = db.table("system_config").select("*").execute()
    return jsonify(result.data or []), 200


@admin_bp.route("/config/<config_key>", methods=["PATCH"])
@require_admin
def update_config(config_key):
    body = request.get_json(silent=True) or {}
    if "config_value" not in body:
        return jsonify({"error": "config_value is required"}), 400

    db = get_db()

    # Check if key exists
    existing = db.table("system_config") \
        .select("id") \
        .eq("config_key", config_key) \
        .maybe_single() \
        .execute()

    if existing.data:
        db.table("system_config").update({
            "config_value": body["config_value"],
            "updated_by":   get_admin_email(g.admin_id),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }).eq("config_key", config_key).execute()
    else:
        # Upsert — create the key if it doesn't exist
        db.table("system_config").insert({
            "config_key":   config_key,
            "config_value": body["config_value"],
            "updated_by":   get_admin_email(g.admin_id),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }).execute()

    _audit(db, "system_config", config_key, "update", f"Set {config_key}")
    return jsonify({"message": "Config updated"}), 200


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN USERS
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/users", methods=["GET"])
@require_admin
def list_users():
    db = get_db()
    result = db.table("admin_users") \
        .select("id, name, email, role, is_active, last_login, created_at") \
        .order("created_at") \
        .execute()
    return jsonify(result.data or []), 200


@admin_bp.route("/users", methods=["POST"])
@require_admin
def create_user():
    body = request.get_json(silent=True) or {}
    if not body.get("email") or not body.get("password") or not body.get("name"):
        return jsonify({"error": "name, email and password are required"}), 400

    pw_hash = bcrypt.hashpw(
        body["password"].encode(), bcrypt.gensalt(rounds=12)).decode()
    db = get_db()

    row = db.table("admin_users").insert({
        "name":          body["name"],
        "email":         body["email"].lower().strip(),
        "password_hash": pw_hash,
        "role":          body.get("role", "editor"),
        "is_active":     True,
    }).execute()

    _audit(db, "admin_users", row.data[0]["id"],
           "insert", f"Created user {body['email']}")
    return jsonify({
        "id":    row.data[0]["id"],
        "name":  row.data[0]["name"],
        "email": row.data[0]["email"],
        "role":  row.data[0]["role"],
    }), 201


@admin_bp.route("/users/<user_id>", methods=["PATCH"])
@require_admin
def update_user(user_id):
    body = request.get_json(silent=True) or {}
    allowed = {"name", "role", "is_active"}
    update = {k: v for k, v in body.items() if k in allowed}

    if "password" in body:
        update["password_hash"] = bcrypt.hashpw(
            body["password"].encode(), bcrypt.gensalt(rounds=12)
        ).decode()

    if not update:
        return jsonify({"error": "No valid fields"}), 400

    db = get_db()
    db.table("admin_users").update(update).eq("id", user_id).execute()
    _audit(db, "admin_users", user_id, "update")
    return jsonify({"message": "User updated"}), 200


@admin_bp.route("/users/<user_id>", methods=["DELETE"])
@require_admin
def delete_user(user_id):
    if user_id == g.admin_id:
        return jsonify({"error": "Cannot delete your own account"}), 400
    db = get_db()
    db.table("admin_users").update(
        {"is_active": False}).eq("id", user_id).execute()
    _audit(db, "admin_users", user_id, "delete", "Deactivated")
    return jsonify({"message": "User deactivated"}), 200


# ══════════════════════════════════════════════════════════════════════════════
# AUDIT LOG
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/audit-log", methods=["GET"])
@require_admin
def audit_log():
    page = int(request.args.get("page",  1))
    per_page = int(request.args.get("limit", 50))
    offset = (page - 1) * per_page
    db = get_db()

    result = db.table("updates_log") \
        .select("*") \
        .order("updated_at", desc=True) \
        .range(offset, offset + per_page - 1) \
        .execute()
    return jsonify(result.data or []), 200


# ══════════════════════════════════════════════════════════════════════════════
# FEEDBACK
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/feedback", methods=["GET"])
@require_admin
def list_feedback():
    page = int(request.args.get("page",  1))
    per_page = int(request.args.get("limit", 20))
    offset = (page - 1) * per_page
    db = get_db()

    result = db.table("feedback") \
        .select("id, chat_log_id, rating, comment, created_at") \
        .order("created_at", desc=True) \
        .range(offset, offset + per_page - 1) \
        .execute()

    # Rating distribution
    all_fb = db.table("feedback").select("rating").execute()
    ratings = [r["rating"] for r in (all_fb.data or []) if r.get("rating")]
    dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for r in ratings:
        if r in dist:
            dist[r] += 1

    return jsonify({
        "items":        result.data or [],
        "distribution": dist,
        "avg_rating":   round(sum(ratings) / len(ratings), 1) if ratings else None,
        "total":        len(ratings),
    }), 200
