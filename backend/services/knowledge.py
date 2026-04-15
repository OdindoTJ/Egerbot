"""
services/knowledge.py
Fetches every knowledge base table from Supabase and formats
the data into a single text block for injection into the LLM prompt.
"""

import json
from supabase import Client


def _section(title: str, data: list) -> str:
    """Format a list of rows as a clearly labelled section."""
    if not data:
        return f"--- {title} ---\n[No data available]\n"
    return f"--- {title} ---\n{json.dumps(data, indent=2, default=str)}\n"


def fetch_university_info(db: Client) -> str:
    rows = db.table("university_information") \
        .select("section, title_en, title_sw, content_en, content_sw, metadata") \
        .eq("active", True) \
        .execute()
    return _section("UNIVERSITY INFORMATION", rows.data)


def fetch_programs(db: Client) -> str:
    rows = db.table("programs") \
        .select(
            "code, name_en, name_sw, faculty, department, level, duration, "
            "kcse_min_grade, cluster_subjects, "
            "career_prospects_en"
        ) \
        .eq("active", True) \
        .order("faculty") \
        .execute()
    return _section("PROGRAMMES (with department, level, KCSE requirements, fees)", rows.data)


def fetch_entry_requirements(db: Client) -> str:
    rows = db.table("entry_requirements") \
        .select(
            "faculty, program_code, min_mean_grade, "
            "cluster_subjects, additional_notes_en, additional_notes_sw"
        ) \
        .execute()
    return _section("ENTRY REQUIREMENTS", rows.data)


def fetch_fee_structures(db: Client) -> str:
    rows = db.table("fee_structures") \
        .select(
            "intake_year, intake_period, tuition_per_year, "
            "other_fees, currency, programs(name_en, code)"
        ) \
        .order("intake_year", desc=True) \
        .execute()
    return _section("FEE STRUCTURES", rows.data)


def fetch_intakes(db: Client) -> str:
    rows = db.table("intakes") \
        .select(
            "year, period, type, opening_date, "
            "closing_date, status, notes_en, notes_sw"
        ) \
        .order("year", desc=True) \
        .execute()
    return _section("INTAKES & APPLICATION WINDOWS", rows.data)


def fetch_faqs(db: Client) -> str:
    rows = db.table("faqs") \
        .select("question_en, question_sw, answer_en, answer_sw, category, tags") \
        .execute()
    return _section("FREQUENTLY ASKED QUESTIONS", rows.data)


def fetch_quick_replies(db: Client) -> str:
    rows = db.table("quick_replies") \
        .select(
            "trigger_category, label_en, label_sw, "
            "message_en, message_sw, display_order"
        ) \
        .eq("is_active", True) \
        .order("display_order") \
        .execute()
    return _section("SUGGESTED QUICK REPLIES", rows.data)


def build_knowledge_base(db: Client) -> str:
    """
    Fetch all knowledge domains and combine into one context string
    ready to be injected into the system prompt.
    """
    sections = [
        fetch_university_info(db),
        fetch_programs(db),
        fetch_entry_requirements(db),
        fetch_fee_structures(db),
        fetch_intakes(db),
        fetch_faqs(db),
        fetch_quick_replies(db),
    ]
    return "\n\n".join(sections)


def get_system_config(db: Client) -> dict:
    """Return all system_config rows as a key → value dict."""
    rows = db.table("system_config") \
        .select("config_key, config_value") \
        .execute()
    return {r["config_key"]: r["config_value"] for r in rows.data}