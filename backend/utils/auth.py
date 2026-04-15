"""
utils/auth.py
Admin authentication decorator and token helpers.
"""

import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from functools import wraps

from flask import request, jsonify, g
from config.supabase import get_db
from config.settings import SESSION_TOKEN_EXPIRE_H


def hash_token(raw_token: str) -> str:
    """SHA-256 hash a raw token for safe storage."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def generate_token() -> str:
    """Generate a cryptographically secure random token."""
    return secrets.token_hex(32)


def create_admin_session(admin_id: str) -> str:
    """
    Insert a new admin_sessions row and return the raw token.
    Only the hash is stored in the database — never the raw token.
    """
    raw_token  = generate_token()
    token_hash = hash_token(raw_token)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(hours=SESSION_TOKEN_EXPIRE_H)
    ).isoformat()

    get_db().table("admin_sessions").insert({
        "admin_id":   admin_id,
        "token_hash": token_hash,
        "expires_at": expires_at,
        "revoked":    False,
    }).execute()

    return raw_token


def revoke_admin_session(raw_token: str):
    """Mark an admin session as revoked."""
    token_hash = hash_token(raw_token)
    get_db().table("admin_sessions") \
        .update({"revoked": True}) \
        .eq("token_hash", token_hash) \
        .execute()


def require_admin(f):
    """
    Route decorator that validates the Authorization: Bearer <token> header.
    Sets g.admin_id on success so route handlers know who is logged in.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")

        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Authorization header missing or malformed"}), 401

        raw_token  = auth_header.split(" ", 1)[1].strip()
        token_hash = hash_token(raw_token)

        db     = get_db()
        result = db.table("admin_sessions") \
            .select("admin_id, expires_at, revoked") \
            .eq("token_hash", token_hash) \
            .limit(1) \
            .execute()

        if not result.data:
            return jsonify({"error": "Invalid token"}), 401

        session = result.data[0]

        if session["revoked"]:
            return jsonify({"error": "Token has been revoked. Please log in again."}), 401

        expires = datetime.fromisoformat(session["expires_at"])
        if datetime.now(timezone.utc) > expires:
            return jsonify({"error": "Token expired. Please log in again."}), 401

        g.admin_id = session["admin_id"]
        return f(*args, **kwargs)

    return decorated


def get_admin_email(admin_id: str) -> str:
    """Helper to fetch the email of a logged-in admin for audit logs."""
    result = get_db().table("admin_users") \
        .select("email") \
        .eq("id", admin_id) \
        .single() \
        .execute()
    return result.data["email"] if result.data else "unknown"
