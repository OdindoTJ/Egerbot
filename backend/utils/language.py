"""
utils/language.py
Detects whether a user message is English or Swahili.
"""

SWAHILI_KEYWORDS = [
    "habari", "ninahitaji", "nataka", "ninaweza", "nini", "wapi",
    "jinsi", "gani", "tafadhali", "asante", "karibu", "chuo",
    "masomo", "ada", "fomu", "daraja", "kujiunga", "ni", "na",
    "ya", "wa", "kwa", "au", "la", "sina", "niko", "uko",
    "elimu", "shahada", "diploma", "fedha", "malipo",
]


def detect_language(text: str) -> str:
    """
    Returns 'sw' if the message appears to be Swahili, else 'en'.
    Uses a simple keyword frequency heuristic.
    """
    lower = text.lower()
    words = lower.split()
    hits  = sum(1 for w in words if w in SWAHILI_KEYWORDS)
    # Threshold: 2+ Swahili keywords in the message → treat as Swahili
    return "sw" if hits >= 2 else "en"
