"""
config/supabase.py
Creates a fresh Supabase client per call to avoid HTTP/2 connection
reuse errors (LocalProtocolError: Trailers must have END_STREAM set)
that occur when multiple concurrent requests share one connection.
"""

from supabase import create_client, Client
from config.settings import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY


def get_db() -> Client:
    """
    Return a fresh Supabase client for each call.
    This avoids HTTP/2 stream reuse errors under concurrent load.
    The supabase-py client is lightweight to create — no connection
    is opened until the first query is executed.
    """
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def test_connection() -> dict:
    """
    Ping Supabase to verify credentials and connectivity.
    Called by /health/full and during startup.
    """
    try:
        db = get_db()
        db.table("system_config").select("config_key").limit(1).execute()
        return {"status": "connected", "error": None}
    except Exception as e:
        return {"status": "error", "error": str(e)}
