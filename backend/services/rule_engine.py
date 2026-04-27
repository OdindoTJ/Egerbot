"""
services/rule_engine.py
═══════════════════════════════════════════════════════════════════════════════
Rule-Based Fallback Engine for EgerBot

This module provides instant, accurate answers to common Egerton University
questions WITHOUT needing any LLM API. It is used as the LAST fallback before
returning "temporarily unavailable" — so the bot ALWAYS answers common questions.

Architecture:
  1. LLM cascade tries: Gemini → Claude
  2. If ALL APIs fail → rule_engine.answer() is tried
  3. Only if rule_engine also has no match → show unavailable message

The rule engine covers ALL question categories that prospective students ask:
  - Fees & payment methods
  - Programmes & courses
  - Entry requirements & KCSE grades
  - Application process (KUCCPS & self-sponsored)
  - Campus life, accommodation, hostels
  - Location & transport
  - Contacts & offices
  - Intake dates
  - Computer Science specifics
  - General university info
═══════════════════════════════════════════════════════════════════════════════
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# INTENT DETECTION — keyword matching
# ══════════════════════════════════════════════════════════════════════════════


def _contains(text: str, *keywords) -> bool:
    """True if ANY keyword appears in text (case-insensitive)."""
    t = text.lower()
    return any(kw.lower() in t for kw in keywords)


def _detect_intent(msg: str) -> Optional[str]:
    """Classify the user's question into a topic bucket."""
    m = msg.lower()

    # ── Fees & Payment ──────────────────────────────────────────────────────
    if _contains(m, "fee", "fees", "tuition", "cost", "how much", "payment",
                 "pay", "mpesa", "bank", "ksh", "kes", "money", "charge",
                 "bei", "malipo", "ada", "lipa"):
        # More specific: payment METHOD
        if _contains(m, "pay", "how to pay", "payment method", "mpesa",
                     "bank", "portal", "student portal", "jinsi ya kulipa"):
            return "fee_payment_methods"
        return "fees_general"

    # ── Entry Requirements ───────────────────────────────────────────────────
    if _contains(m, "requirement", "kcse", "grade", "cluster", "subject",
                 "qualify", "minimum", "cutoff", "cut off", "c+", "b plain",
                 "entry", "join", "admission grade", "daraja", "sifa",
                 "kiwango", "masharti"):
        return "entry_requirements"

    # ── Application Process ──────────────────────────────────────────────────
    if _contains(m, "apply", "application", "kuccps", "self-sponsored",
                 "government sponsored", "how do i join", "how to apply",
                 "admission process", "ombi", "jinsi ya kuomba", "wasilisha"):
        return "application_process"

    # ── Programmes & Courses ─────────────────────────────────────────────────
    if _contains(m, "programme", "program", "course", "degree", "diploma",
                 "bachelor", "master", "phd", "faculty", "department",
                 "computer science", "engineering", "agriculture", "education",
                 "law", "medicine", "nursing", "business", "it ", "ict",
                 "masomo", "chuo", "shahada", "kozi", "kitengo"):
        # Computer Science specifically
        if _contains(m, "computer science", "cs ", "computer", "software",
                     "programming", "it ", "ict", "information technology"):
            return "computer_science"
        return "programmes_general"

    # ── Intake & Deadlines ───────────────────────────────────────────────────
    if _contains(m, "intake", "deadline", "when", "date", "semester",
                 "academic year", "next intake", "2025", "2026",
                 "tarehe", "lini", "mwaka"):
        return "intake_dates"

    # ── Accommodation & Hostels ──────────────────────────────────────────────
    if _contains(m, "hostel", "accommodation", "room", "housing",
                 "residential", "where to stay", "nyumba", "bweni",
                 "kulala", "makazi"):
        return "accommodation"

    # ── Campus Life ──────────────────────────────────────────────────────────
    if _contains(m, "campus", "life", "clubs", "activities", "sport",
                 "library", "health", "clinic", "maisha", "shughuli",
                 "michezo"):
        return "campus_life"

    # ── Location & Transport ─────────────────────────────────────────────────
    if _contains(m, "location", "where is", "how to get", "direction",
                 "nakuru", "njoro", "nairobi", "bus", "matatu", "transport",
                 "uko wapi", "safari", "umbali", "mahali"):
        return "location"

    # ── Contacts & Offices ───────────────────────────────────────────────────
    if _contains(m, "contact", "phone", "email", "address", "office",
                 "admissions office", "registrar", "call", "reach",
                 "nambari", "simu", "barua pepe", "ofisi"):
        return "contacts"

    # ── Scholarships & Financial Aid ─────────────────────────────────────────
    if _contains(m, "scholarship", "bursary", "loan", "helb", "fund",
                 "financial aid", "sponsor", "bursari", "mkopo", "msaada"):
        return "scholarships"

    # ── About Egerton ────────────────────────────────────────────────────────
    if _contains(m, "about", "history", "founded", "established", "egerton",
                 "university", "ranking", "accredit", "kuhusu", "chuo kikuu"):
        return "about_egerton"

    # ── Greeting ─────────────────────────────────────────────────────────────
    if _contains(m, "hello", "hi", "hey", "good morning", "good afternoon",
                 "good evening", "habari", "jambo", "hujambo", "salam"):
        return "greeting"

    return None


# ══════════════════════════════════════════════════════════════════════════════
# RESPONSE TEMPLATES — bilingual (en / sw)
# ══════════════════════════════════════════════════════════════════════════════

RESPONSES = {

    "greeting": {
        "en": (
            "Hello! 👋 Welcome to Egerton University. I'm EgerBot, your guide to "
            "joining and navigating Egerton. I can help you with:\n\n"
            "- **Programmes & courses** offered\n"
            "- **KCSE entry requirements** for each programme\n"
            "- **Fees & payment methods**\n"
            "- **Application process** (KUCCPS & self-sponsored)\n"
            "- **Accommodation & hostels**\n"
            "- **Campus location & contacts**\n\n"
            "What would you like to know?"
        ),
        "sw": (
            "Habari! 👋 Karibu Chuo Kikuu cha Egerton. Mimi ni EgerBot, mwongozo "
            "wako wa kujiunga na kusafiri Egerton. Ninaweza kukusaidia na:\n\n"
            "- **Programu na kozi** zinazopatikana\n"
            "- **Mahitaji ya KCSE** kwa kila programu\n"
            "- **Ada na njia za malipo**\n"
            "- **Mchakato wa maombi** (KUCCPS na kujisponsor)\n"
            "- **Malazi na bweni**\n"
            "- **Mahali chuo kiko na mawasiliano**\n\n"
            "Ungependa kujua nini?"
        ),
    },

    "fees_general": {
        "en": (
            "**Egerton University Fees (2025/2026)**\n\n"
            "Fees vary by programme, year of study, and student category. "
            "General estimates are:\n\n"
            "**Government-Sponsored (KUCCPS) Students:**\n"
            "- Accommodation: KES 15,000–20,000 per semester\n"
            "- Medical levy: KES 2,000 per year\n"
            "- Student union fee: KES 1,000 per year\n"
            "- Activity fees: KES 2,500 per semester\n"
            "*(Tuition is covered by the government)*\n\n"
            "**Self-Sponsored Students:**\n"
            "- Tuition: KES 60,000–120,000 per year (varies by programme)\n"
            "- Science/Engineering programmes: KES 90,000–150,000 per year\n"
            "- Accommodation: KES 15,000–20,000 per semester\n"
            "- Registration & other levies: approx. KES 25,000 per year\n\n"
            "💡 For **exact fees** for your specific programme, contact the Finance Office:\n"
            "📧 finance@egerton.ac.ke | 📞 +254 51 221 3018\n"
            "Or visit: **www.egerton.ac.ke/fees**\n\n"
            "*Always verify current fees with the Finance Office as they may be updated annually.*"
        ),
        "sw": (
            "**Ada za Chuo Kikuu cha Egerton (2025/2026)**\n\n"
            "Ada zinategemea programu, mwaka wa masomo, na aina ya mwanafunzi. "
            "Makadirio ya jumla ni:\n\n"
            "**Wanafunzi wa Serikali (KUCCPS):**\n"
            "- Malazi: KES 15,000–20,000 kwa semester\n"
            "- Karo ya matibabu: KES 2,000 kwa mwaka\n"
            "- Ada ya muungano wa wanafunzi: KES 1,000 kwa mwaka\n"
            "- Ada za shughuli: KES 2,500 kwa semester\n"
            "*(Karo ya masomo inafunikwa na serikali)*\n\n"
            "**Wanafunzi wa Kujisponsor:**\n"
            "- Karo: KES 60,000–120,000 kwa mwaka (inategemea programu)\n"
            "- Programu za Sayansi/Uhandisi: KES 90,000–150,000 kwa mwaka\n"
            "- Malazi: KES 15,000–20,000 kwa semester\n"
            "- Usajili na malipo mengine: takriban KES 25,000 kwa mwaka\n\n"
            "💡 Kwa **ada halisi** za programu yako, wasiliana na Ofisi ya Fedha:\n"
            "📧 finance@egerton.ac.ke | 📞 +254 51 221 3018\n\n"
            "*Thibitisha ada za sasa na Ofisi ya Fedha kwani zinaweza kubadilika kila mwaka.*"
        ),
    },

    "fee_payment_methods": {
        "en": (
            "**How to Pay Fees at Egerton University**\n\n"
            "Egerton University accepts fees through the following methods:\n\n"

            "**1. Bank Deposit**\n"
            "- Bank: KCB / Equity / Co-operative Bank\n"
            "- Account Name: Egerton University\n"
            "- Deposit slip must include your **registration number**\n\n"
            "**2. Student Portal (Online)**\n"
            "- Log in at: **portal.egerton.ac.ke**\n"
            "- Navigate to Finance → Make Payment\n"
            "- Supports card payments (Visa/Mastercard)\n\n"
            "**3. Finance Office (Cheque)**\n"
            "- Location: Administration Block, Main Campus, Njoro\n"
            "- Hours: Monday–Friday, 8:00 AM – 5:00 PM\n\n"
            "⚠️ Always keep your payment receipt/SMS as proof of payment.\n"
            "📞 Finance queries: +254 51 221 3018 | finance@egerton.ac.ke"
        ),
        "sw": (
            "**Jinsi ya Kulipa Ada Egerton University**\n\n"
            "Chuo Kikuu cha Egerton kinakubali malipo kupitia njia zifuatazo:\n\n"

            "**1. Amana ya Benki**\n"
            "- Benki: KCB / Equity / Co-operative Bank\n"
            "- Jina la Akaunti: Egerton University\n"
            "- Stakabadhi lazima iandike **nambari yako ya usajili**\n\n"
            "**2. Portal ya Wanafunzi (Mtandaoni)**\n"
            "- Ingia: **portal.egerton.ac.ke**\n"
            "- Nenda Fedha → Lipa\n"
            "- Inakubali kadi za benki (Visa/Mastercard)\n\n"
            "**3. Ofisi ya Fedha (Nauli/Hundi)**\n"
            "- Mahali: Jengo la Utawala, Campus Kuu, Njoro\n"
            "- Masaa: Jumatatu–Ijumaa, 8:00 asubuhi – 5:00 jioni\n\n"
            "⚠️ Hifadhi stakabadhi/SMS yako kama uthibitisho wa malipo.\n"
            "📞 Maswali ya fedha: +254 51 221 3018 | finance@egerton.ac.ke"
        ),
    },

    "entry_requirements": {
        "en": (
            "**Egerton University Entry Requirements**\n\n"
            "The minimum general requirement is a **KCSE Mean Grade of C+ (Plus)**.\n\n"
            "**By Programme Category:**\n\n"
            "🔬 **Science & Engineering Programmes** (BSc Agriculture, Engineering, Computer Science, etc.)\n"
            "- Minimum: **B Plain** overall + relevant cluster subjects\n"
            "- Key cluster subjects: Mathematics, Physics/Chemistry/Biology\n\n"
            "📚 **Arts & Social Sciences** (Education, Development Studies, etc.)\n"
            "- Minimum: **C+** overall\n"
            "- English/Kiswahili required at C+ or above\n\n"
            "💊 **Health Sciences** (Nursing, Environmental Health)\n"
            "- Minimum: **B Plain** overall\n"
            "- Biology + Chemistry required at B Plain\n\n"
            "💼 **Business & Commerce**\n"
            "- Minimum: **C+** overall\n"
            "- Mathematics required at C+\n\n"
            "📖 **Education Programmes**\n"
            "- Minimum: **C+** overall\n"
            "- Subject-specific requirements depend on teaching subjects\n\n"
            "**Self-Sponsored Students:** Minimum **C Plain** for most programmes.\n\n"
            "💡 For your specific programme's requirements, ask me: \"What are the requirements for [programme name]?\"\n"
            "Or contact Admissions: 📧 admissions@egerton.ac.ke | 📞 +254 51 221 3018"
        ),
        "sw": (
            "**Mahitaji ya Kujiunga Chuo Kikuu cha Egerton**\n\n"
            "Daraja la chini la jumla la KCSE linalohitajika ni **C+ (Plus)**.\n\n"
            "**Kwa Aina ya Programu:**\n\n"
            "🔬 **Sayansi na Uhandisi** (BSc Kilimo, Uhandisi, Sayansi ya Kompyuta, n.k.)\n"
            "- Kiwango cha chini: **B Plain** kwa jumla + masomo ya kundi husika\n"
            "- Masomo ya kundi: Hisabati, Fizikia/Kemia/Biolojia\n\n"
            "📚 **Sanaa na Sayansi za Jamii** (Elimu, Maendeleo, n.k.)\n"
            "- Kiwango cha chini: **C+** kwa jumla\n"
            "- Kiingereza/Kiswahili inahitajika kwa C+ au zaidi\n\n"
            "💊 **Sayansi za Afya** (Uuguzi, Afya ya Mazingira)\n"
            "- Kiwango cha chini: **B Plain** kwa jumla\n"
            "- Biolojia + Kemia zinahitajika kwa B Plain\n\n"
            "💼 **Biashara na Uchumi**\n"
            "- Kiwango cha chini: **C+** kwa jumla\n"
            "- Hisabati inahitajika kwa C+\n\n"
            "💡 Kwa mahitaji ya programu yako maalum, niulize: \"Mahitaji ya [jina la programu] ni nini?\"\n"
            "Au wasiliana na Udahili: 📧 admissions@egerton.ac.ke | 📞 +254 51 221 3018"
        ),
    },

    "application_process": {
        "en": (
            "**How to Apply to Egerton University**\n\n"
            "There are **two pathways** to join Egerton:\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "**PATH 1: KUCCPS (Government-Sponsored)**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "1. Sit KCSE and wait for your results\n"
            "2. Visit **kuccps.net** and log in with your KCSE index number\n"
            "3. Select your course choices (up to 6 programmes, ranked)\n"
            "4. Pay the application fee (approx. KES 1,500) via M-Pesa\n"
            "5. Submit and wait for placement results\n"
            "6. If placed at Egerton, report on the official reporting date\n"
            "7. Complete registration online at **portal.egerton.ac.ke**\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "**PATH 2: Self-Sponsored (Private)**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "1. Visit **application.egerton.ac.ke**\n"
            "2. Create an account and fill in the application form\n"
            "3. Upload: KCSE certificate/results slip, national ID/birth certificate, passport photo\n"
            "4. Pay application fee: **KES 2,000** via M-Pesa (Paybill 222999, A/C: APPLICATION)\n"
            "5. Submit your application online\n"
            "6. Check your application status on the portal\n"
            "7. If admitted, pay fees and report on the given date\n\n"
            "📅 **Current Intake:** Applications for 2025/2026 are open.\n"
            "📧 admissions@egerton.ac.ke | 📞 +254 51 221 3018\n"
            "🌐 www.egerton.ac.ke/admissions"
        ),
        "sw": (
            "**Jinsi ya Kuomba Kujiunga Chuo Kikuu cha Egerton**\n\n"
            "Kuna **njia mbili** za kujiunga na Egerton:\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "**NJIA 1: KUCCPS (Wanafunzi wa Serikali)**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "1. Fanya KCSE na subiri matokeo yako\n"
            "2. Tembelea **kuccps.net** na ingia na nambari yako ya KCSE\n"
            "3. Chagua kozi (hadi 6 programu, kwa mpangilio)\n"
            "4. Lipa ada ya maombi (takriban KES 1,500) kupitia M-Pesa\n"
            "5. Wasilisha na subiri matokeo ya uwekaji\n"
            "6. Ukipewa nafasi Egerton, ripoti siku rasmi ya kuripoti\n"
            "7. Kamilisha usajili mtandaoni kwenye **portal.egerton.ac.ke**\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "**NJIA 2: Kujisponsor (Binafsi)**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "1. Tembelea **application.egerton.ac.ke**\n"
            "2. Unda akaunti na jaza fomu ya maombi\n"
            "3. Pakia: cheti/slip ya KCSE, kitambulisho/cheti cha kuzaliwa, picha ya pasipoti\n"
            "4. Lipa ada ya maombi: **KES 2,000** kupitia M-Pesa (Paybill 222999, A/C: APPLICATION)\n"
            "5. Wasilisha maombi yako mtandaoni\n\n"
            "📅 **Ulizaji wa Sasa:** Maombi ya 2025/2026 yamefunguliwa.\n"
            "📧 admissions@egerton.ac.ke | 📞 +254 51 221 3018"
        ),
    },

    "computer_science": {
        "en": (
            "**Bachelor of Science in Computer Science — Egerton University**\n\n"
            "**Programme Overview:**\n"
            "A 4-year degree programme offered by the **School of Computing and Informatics** "
            "under the Faculty of Science. It equips students with software development, "
            "networking, database management, AI, and cybersecurity skills.\n\n"
            "**Entry Requirements:**\n"
            "- KCSE Mean Grade: **B Plain** minimum\n"
            "- Mathematics: **B Plain** minimum\n"
            "- Physics: **C+** minimum\n"
            "- English: **C+** minimum\n\n"
            "**Programme Duration:** 4 years (8 semesters)\n\n"
            "**Key Units Covered:**\n"
            "Programming (Python, Java, C++), Data Structures, Databases, Networking, "
            "Operating Systems, Software Engineering, Artificial Intelligence, Cybersecurity, "
            "Web Development, Mobile Application Development\n\n"
            "**Career Prospects:**\n"
            "Software Developer, Systems Analyst, Database Administrator, Network Engineer, "
            "Cybersecurity Analyst, IT Consultant, Data Scientist\n\n"
            "**Fees (Self-Sponsored):** Approx. KES 90,000–110,000 per year\n"
            "**Fees (Government):** Accommodation + levies only (~KES 40,000 per year)\n\n"
            "📧 cs@egerton.ac.ke | 📞 +254 51 221 3018\n"
            "🌐 www.egerton.ac.ke/courses/computer-science"
        ),
        "sw": (
            "**Shahada ya Sayansi ya Kompyuta — Chuo Kikuu cha Egerton**\n\n"
            "**Muhtasari wa Programu:**\n"
            "Programu ya miaka 4 inayotolewa na **Shule ya Kompyuta na Taarifa** "
            "chini ya Kitivo cha Sayansi.\n\n"
            "**Mahitaji ya Kujiunga:**\n"
            "- Daraja la KCSE: **B Plain** angalau\n"
            "- Hisabati: **B Plain** angalau\n"
            "- Fizikia: **C+** angalau\n"
            "- Kiingereza: **C+** angalau\n\n"
            "**Muda wa Programu:** Miaka 4 (semesta 8)\n\n"
            "**Maeneo ya Kusoma:**\n"
            "Uprogramu (Python, Java, C++), Miundo ya Data, Hifadhidata, Mitandao, "
            "Mifumo ya Uendeshaji, Uhandisi wa Programu, Akili Bandia, Usalama wa Mtandao\n\n"
            "**Fursa za Kazi:**\n"
            "Mtengenezaji Programu, Mchambuzi wa Mifumo, DBA, Mhandisi wa Mitandao, Mtaalam wa Usalama wa Mtandao\n\n"
            "**Ada (Kujisponsor):** Takriban KES 90,000–110,000 kwa mwaka\n\n"
            "📧 cs@egerton.ac.ke | 📞 +254 51 221 3018"
        ),
    },

    "programmes_general": {
        "en": (
            "**Programmes Offered at Egerton University**\n\n"
            "Egerton University offers **over 70 undergraduate and postgraduate programmes** "
            "across its faculties. Key faculties include:\n\n"
            "🌱 **Faculty of Agriculture** — BSc Agriculture, Agricultural Economics, "
            "Horticulture, Animal Science, Agribusiness Management\n\n"
            "💻 **Faculty of Science** — Computer Science, Mathematics, Statistics, "
            "Physics, Chemistry, Biology, Environmental Science\n\n"
            "⚙️ **Faculty of Engineering & Technology** — Civil Engineering, "
            "Electrical Engineering, Mechanical Engineering, Agricultural Engineering\n\n"
            "📚 **Faculty of Education** — Education (various teaching subjects)\n\n"
            "🏥 **Faculty of Health Sciences** — Environmental Health, Nursing\n\n"
            "🏛️ **Faculty of Arts & Social Sciences** — Development Studies, "
            "Sociology, History, Kiswahili, English\n\n"
            "💼 **Faculty of Commerce** — Commerce, Cooperative Management, "
            "Agribusiness\n\n"
            "📖 **Faculty of Law** — LLB (Bachelor of Laws)\n\n"
            "Would you like details on a **specific programme**? Just ask, for example: "
            "\"Tell me about the Computer Science programme\" or "
            "\"What are the requirements for Agriculture?\""
        ),
        "sw": (
            "**Programu Zinazotolewa na Chuo Kikuu cha Egerton**\n\n"
            "Chuo Kikuu cha Egerton kinatoa **zaidi ya programu 70** "
            "za shahada na uzamili. Vitivo vikuu ni:\n\n"
            "🌱 **Kitivo cha Kilimo** — BSc Kilimo, Uchumi wa Kilimo, Bustani, Mifugo\n\n"
            "💻 **Kitivo cha Sayansi** — Sayansi ya Kompyuta, Hisabati, Takwimu, "
            "Fizikia, Kemia, Biolojia, Sayansi ya Mazingira\n\n"
            "⚙️ **Kitivo cha Uhandisi** — Uhandisi wa Kiraia, Uhandisi wa Umeme, "
            "Uhandisi wa Mitambo\n\n"
            "📚 **Kitivo cha Elimu** — Elimu (masomo mbalimbali ya kufundisha)\n\n"
            "🏥 **Kitivo cha Sayansi za Afya** — Uuguzi, Afya ya Mazingira\n\n"
            "💼 **Kitivo cha Biashara** — Uchumi wa Ushirika, Biashara\n\n"
            "Je, ungependa maelezo ya **programu maalum**? Niulize, kwa mfano: "
            "\"Niambie kuhusu programu ya Sayansi ya Kompyuta\""
        ),
    },

    "intake_dates": {
        "en": (
            "**Egerton University Intake Dates 2025/2026**\n\n"
            "**First Semester (September Intake)**\n"
            "- KUCCPS Applications: June – July 2025\n"
            "- Self-Sponsored Applications: May – August 2025\n"
            "- Reporting/Orientation Date: **September 2025** (exact date TBA)\n"
            "- Lectures Begin: October 2025\n\n"
            "**Second Semester (January/February Intake)**\n"
            "- Applications: October – November 2025\n"
            "- Reporting Date: **January/February 2026**\n\n"
            "**Current Status:**\n"
            "📢 **2025/2026 Applications are currently OPEN** for both KUCCPS and "
            "Self-Sponsored students.\n\n"
            "🌐 Apply at: **application.egerton.ac.ke**\n"
            "📧 admissions@egerton.ac.ke | 📞 +254 51 221 3018\n\n"
            "*Confirm exact reporting dates on the official Egerton website or with the Admissions Office.*"
        ),
        "sw": (
            "**Tarehe za Ulizaji wa Chuo Kikuu cha Egerton 2025/2026**\n\n"
            "**Semester ya Kwanza (Ulizaji wa Septemba)**\n"
            "- Maombi ya KUCCPS: Juni – Julai 2025\n"
            "- Maombi ya Kujisponsor: Mei – Agosti 2025\n"
            "- Tarehe ya Kuripoti: **Septemba 2025** (tarehe halisi bado)\n"
            "- Masomo Yanaanza: Oktoba 2025\n\n"
            "**Semester ya Pili (Ulizaji wa Januari/Februari)**\n"
            "- Maombi: Oktoba – Novemba 2025\n"
            "- Tarehe ya Kuripoti: **Januari/Februari 2026**\n\n"
            "**Hali ya Sasa:**\n"
            "📢 **Maombi ya 2025/2026 yamefunguliwa** kwa wanafunzi wa KUCCPS na Kujisponsor.\n\n"
            "🌐 Omba kwenye: **application.egerton.ac.ke**\n"
            "📧 admissions@egerton.ac.ke | 📞 +254 51 221 3018"
        ),
    },

    "accommodation": {
        "en": (
            "**Accommodation at Egerton University**\n\n"
            "Egerton University has **on-campus residential halls (hostels)** for both "
            "male and female students on the main campus in Njoro.\n\n"
            "**Available Hostels:**\n"
            "- Several blocks of modern student hostels\n"
            "- Separate halls for male and female students\n"
            "- Options: single rooms, double rooms, and dormitory-style\n\n"
            "**Hostel Fees:**\n"
            "- Single room: approx. KES 17,000–22,000 per semester\n"
            "- Double room (shared): approx. KES 12,000–15,000 per semester\n"
            "- Includes water, electricity, and basic furniture\n\n"
            "**Facilities:**\n"
            "- Study rooms, common rooms, laundry areas\n"
            "- 24-hour security\n"
            "- Close to lecture halls and the library\n\n"
            "**Note:** Hostels are allocated on a first-come, first-served basis "
            "after fee payment. Not all students are guaranteed on-campus accommodation.\n\n"
            "**Off-Campus Options:**\n"
            "Many students rent affordable rooms in Njoro town (1–3 km from campus) "
            "at KES 3,000–8,000 per month.\n\n"
            "📧 accommodation@egerton.ac.ke | 📞 +254 51 221 3018"
        ),
        "sw": (
            "**Malazi ya Chuo Kikuu cha Egerton**\n\n"
            "Chuo Kikuu cha Egerton kina **bweni za ndani ya chuo** kwa wanafunzi "
            "wanaume na wanawake kwenye kampasi kuu mjini Njoro.\n\n"
            "**Bweni Zinazopatikana:**\n"
            "- Vizuizi kadhaa vya bweni za kisasa\n"
            "- Bweni tofauti kwa wanafunzi wanaume na wanawake\n"
            "- Chaguo: vyumba vya mtu mmoja, viwili, au chumba kikubwa\n\n"
            "**Ada za Bweni:**\n"
            "- Chumba cha mtu mmoja: takriban KES 17,000–22,000 kwa semester\n"
            "- Chumba cha watu wawili: takriban KES 12,000–15,000 kwa semester\n"
            "- Inajumuisha maji, umeme, na samani za msingi\n\n"
            "📧 accommodation@egerton.ac.ke | 📞 +254 51 221 3018"
        ),
    },

    "campus_life": {
        "en": (
            "**Campus Life at Egerton University**\n\n"
            "Egerton University offers a vibrant campus life on its main campus in Njoro:\n\n"
            "🏅 **Sports & Recreation**\n"
            "- Football, basketball, volleyball, athletics fields\n"
            "- Swimming pool\n"
            "- Fully equipped gymnasium\n\n"
            "📚 **Academic Facilities**\n"
            "- Main library with over 100,000 volumes and digital resources\n"
            "- Computer labs (free access for students)\n"
            "- Research laboratories and science workshops\n\n"
            "🏥 **Health Services**\n"
            "- Student Health Unit on campus\n"
            "- Subsidised medical care for registered students\n\n"
            "🎭 **Clubs & Societies**\n"
            "- Over 30 registered student clubs: drama, music, debate, "
            "entrepreneurship, environmental, community service, and more\n\n"
            "🍽️ **Cafeterias**\n"
            "- Multiple cafeterias on campus offering affordable meals\n"
            "- Special dietary options available\n\n"
            "📡 **Connectivity**\n"
            "- Free Wi-Fi in library, computer labs, and lecture halls\n\n"
            "The university also has a **student union (EUSU)** that coordinates "
            "student welfare, events, and advocacy."
        ),
        "sw": (
            "**Maisha ya Chuo Kikuu cha Egerton**\n\n"
            "Chuo Kikuu cha Egerton kinatoa maisha ya kuchekesha kwenye kampasi yake kuu mjini Njoro:\n\n"
            "🏅 **Michezo na Burudani**\n"
            "- Viwanja vya mpira, kikapu, voliboli, atletiki\n"
            "- Bwawa la kuogelea\n"
            "- Ukumbi wa mazoezi\n\n"
            "📚 **Vifaa vya Masomo**\n"
            "- Maktaba kuu yenye rasilimali nyingi za kidijitali\n"
            "- Maabara ya kompyuta (bure kwa wanafunzi)\n\n"
            "🏥 **Huduma za Afya**\n"
            "- Kituo cha Afya kwa Wanafunzi kwenye kampasi\n\n"
            "🎭 **Vilabu na Vikundi**\n"
            "- Zaidi ya vilabu 30 vilivyosajiliwa: drama, muziki, mijadala, na zaidi"
        ),
    },

    "location": {
        "en": (
            "**Egerton University — Location & How to Get There**\n\n"
            "📍 **Main Campus Address:**\n"
            "Egerton University, Njoro Campus\n"
            "P.O. Box 536 – 20115, Njoro, Nakuru County, Kenya\n\n"
            "**Where is Njoro?**\n"
            "Njoro is a town approximately **20 km from Nakuru City** and "
            "**about 180 km from Nairobi** via the Nairobi–Nakuru highway.\n\n"
            "**How to Get There:**\n\n"
            "🚌 **From Nairobi:**\n"
            "- Take a bus/matatu from Nairobi's **Machakos Bus Terminal** or "
            "**Afrikke Bus** to Nakuru (fare: approx. KES 350–700)\n"
            "- From Nakuru town, take a **matatu to Njoro** (fare: approx. KES 50–80)\n"
            "- Total journey: approximately 3–4 hours\n\n"
            "🚌 **From Nakuru City:**\n"
            "- Matatus to Njoro depart from **Afraha Stadium stage**\n"
            "- Journey time: approx. 30–45 minutes\n\n"
            "🗺️ **GPS Coordinates:** -0.3458° S, 35.9321° E\n\n"
            "**Other Campuses:**\n"
            "- **Nairobi Campus:** Ralph Bunche Road, Nairobi\n"
            "- **Nakuru Town Campus:** Near Nakuru CBD\n\n"
            "📞 +254 51 221 3018 | 📧 info@egerton.ac.ke"
        ),
        "sw": (
            "**Chuo Kikuu cha Egerton — Mahali na Jinsi ya Kufika**\n\n"
            "📍 **Anwani ya Kampasi Kuu:**\n"
            "Chuo Kikuu cha Egerton, Kampasi ya Njoro\n"
            "S.L.P. 536 – 20115, Njoro, Kaunti ya Nakuru, Kenya\n\n"
            "**Wapi ni Njoro?**\n"
            "Njoro ni mji ulio umbali wa takriban **kilomita 20 kutoka Mji wa Nakuru** "
            "na **takriban kilomita 180 kutoka Nairobi**.\n\n"
            "**Jinsi ya Kufika:**\n\n"
            "🚌 **Kutoka Nairobi:**\n"
            "- Chukua basi/matatu kutoka **Machakos Bus Terminal** Nairobi kwenda Nakuru\n"
            "- Kutoka Nakuru, chukua **matatu kwenda Njoro** (nauli: takriban KES 50–80)\n"
            "- Safari nzima: takriban masaa 3–4\n\n"
            "📞 +254 51 221 3018 | 📧 info@egerton.ac.ke"
        ),
    },

    "contacts": {
        "en": (
            "**Egerton University — Key Contacts**\n\n"
            "📞 **Main Switchboard:** +254 51 221 3018\n"
            "📧 **General Enquiries:** info@egerton.ac.ke\n"
            "🌐 **Website:** www.egerton.ac.ke\n\n"
            "**Specific Offices:**\n\n"
            "🎓 **Admissions Office**\n"
            "📧 admissions@egerton.ac.ke | 📞 +254 51 221 3018 Ext. 2021\n"
            "*(Programme applications, placement, reporting dates)*\n\n"
            "💰 **Finance Office**\n"
            "📧 finance@egerton.ac.ke | 📞 +254 51 221 3018 Ext. 2045\n"
            "*(Fees, payment receipts, financial clearance)*\n\n"
            "📋 **Academic Registrar**\n"
            "📧 registrar@egerton.ac.ke | 📞 +254 51 221 3018 Ext. 2031\n"
            "*(Academic records, transcripts, graduation)*\n\n"
            "🏠 **Accommodation Office**\n"
            "📧 accommodation@egerton.ac.ke\n"
            "*(Hostel allocation, room applications)*\n\n"
            "📍 **Physical Address:**\n"
            "Egerton University, Njoro Campus, P.O. Box 536-20115, Njoro, Kenya\n\n"
            "⏰ **Office Hours:** Monday–Friday, 8:00 AM – 5:00 PM"
        ),
        "sw": (
            "**Mawasiliano Muhimu — Chuo Kikuu cha Egerton**\n\n"
            "📞 **Simu Kuu:** +254 51 221 3018\n"
            "📧 **Maswali ya Jumla:** info@egerton.ac.ke\n"
            "🌐 **Tovuti:** www.egerton.ac.ke\n\n"
            "**Ofisi Maalum:**\n\n"
            "🎓 **Ofisi ya Udahili**\n"
            "📧 admissions@egerton.ac.ke | 📞 +254 51 221 3018\n"
            "*(Maombi ya programu, uwekaji, tarehe za kuripoti)*\n\n"
            "💰 **Ofisi ya Fedha**\n"
            "📧 finance@egerton.ac.ke\n"
            "*(Ada, stakabadhi za malipo, ulinganifu wa fedha)*\n\n"
            "⏰ **Masaa ya Kazi:** Jumatatu–Ijumaa, 8:00 asubuhi – 5:00 jioni"
        ),
    },

    "scholarships": {
        "en": (
            "**Scholarships & Financial Aid at Egerton University**\n\n"
            "Several funding opportunities are available to Egerton students:\n\n"
            "🏦 **1. Higher Education Loans Board (HELB)**\n"
            "- Available to Kenyan citizens in government-sponsored programmes\n"
            "- Loan amounts: KES 50,000–60,000 per year (repayable after graduation)\n"
            "- Apply at: **helb.co.ke** (applications open annually)\n"
            "- Also includes a bursary component (non-repayable) for needy students\n\n"
            "🏛️ **2. University Bursary Fund**\n"
            "- Egerton University has a bursary fund for needy students\n"
            "- Apply through the Student Welfare Office\n"
            "- Awarded based on financial need\n\n"
            "🌍 **3. Government Scholarships**\n"
            "- Presidential Scholarship for top KCSE performers\n"
            "- County government bursaries (apply through your county office)\n"
            "- Ministry of Education scholarships (advertised annually)\n\n"
            "🏢 **4. Private & Corporate Scholarships**\n"
            "- Safaricom Foundation, Equity Wings to Fly, "
            "KenGen Foundation, and other NGO scholarships\n"
            "- These are advertised on the university notice boards and website\n\n"
            "📋 **How to Apply:**\n"
            "Contact the Dean of Students Office:\n"
            "📧 studentwelfare@egerton.ac.ke | 📞 +254 51 221 3018\n\n"
            "💡 Always apply for HELB early — applications open in May each year."
        ),
        "sw": (
            "**Ufadhili na Mikopo — Chuo Kikuu cha Egerton**\n\n"
            "Kuna fursa kadhaa za ufadhili kwa wanafunzi wa Egerton:\n\n"
            "🏦 **1. Bodi ya Mikopo ya Elimu ya Juu (HELB)**\n"
            "- Inapatikana kwa raia wa Kenya katika programu za serikali\n"
            "- Kiasi cha mkopo: KES 50,000–60,000 kwa mwaka (lipa baada ya kuhitimu)\n"
            "- Omba kwenye: **helb.co.ke**\n\n"
            "🏛️ **2. Mfuko wa Bursari ya Chuo**\n"
            "- Egerton ina mfuko wa bursari kwa wanafunzi wahitaji\n"
            "- Omba kupitia Ofisi ya Ustawi wa Wanafunzi\n\n"
            "🏢 **3. Ufadhili wa Sekta Binafsi**\n"
            "- Mfuko wa Safaricom, Equity Wings to Fly, na wengine\n\n"
            "📧 studentwelfare@egerton.ac.ke | 📞 +254 51 221 3018"
        ),
    },

    "about_egerton": {
        "en": (
            "**About Egerton University**\n\n"
            "Egerton University is one of Kenya's **oldest and most prestigious public universities**.\n\n"
            "📅 **Founded:** 1939 (as Egerton Farm School)\n"
            "🏛️ **University Status Granted:** 1987\n"
            "📍 **Main Campus:** Njoro, Nakuru County, Kenya\n"
            "👥 **Student Population:** Over 20,000 students\n"
            "📚 **Programmes:** 70+ undergraduate and postgraduate programmes\n\n"
            "**Faculties & Schools:**\n"
            "Agriculture, Science, Engineering & Technology, Education, "
            "Health Sciences, Arts & Social Sciences, Commerce, Law, "
            "Graduate School, and several institutes\n\n"
            "**Strengths:**\n"
            "Egerton is particularly renowned for agricultural research, "
            "engineering, and natural sciences. It has extensive farm land "
            "for practical agricultural training.\n\n"
            "**Accreditation:**\n"
            "Fully accredited by the **Commission for University Education (CUE)** of Kenya\n\n"
            "**Motto:** *'Advancing Knowledge for Development'*\n\n"
            "🌐 www.egerton.ac.ke | 📞 +254 51 221 3018\n"
            "📍 P.O. Box 536-20115, Njoro, Nakuru County"
        ),
        "sw": (
            "**Kuhusu Chuo Kikuu cha Egerton**\n\n"
            "Chuo Kikuu cha Egerton ni moja ya vyuo vikuu **vya zamani na vya hadhi** zaidi nchini Kenya.\n\n"
            "📅 **Kilianzishwa:** 1939 (kama Shule ya Kilimo ya Egerton)\n"
            "🏛️ **Hadhi ya Chuo Kikuu:** 1987\n"
            "📍 **Kampasi Kuu:** Njoro, Kaunti ya Nakuru, Kenya\n"
            "👥 **Idadi ya Wanafunzi:** Zaidi ya wanafunzi 20,000\n"
            "📚 **Programu:** Zaidi ya 70 za shahada na uzamili\n\n"
            "**Kaulimuli:** *'Advancing Knowledge for Development'*\n\n"
            "🌐 www.egerton.ac.ke | 📞 +254 51 221 3018"
        ),
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def answer(user_message: str, language: str = "en") -> Optional[str]:
    """
    Try to answer user_message using rule-based matching.

    Returns a pre-written response string if we have a match, or None if
    the question is outside our coverage (triggering escalation).

    Args:
        user_message: The user's raw text input
        language: "en" or "sw"

    Returns:
        str: A bilingual-appropriate answer, or None if no match
    """
    if not user_message or not user_message.strip():
        return None

    intent = _detect_intent(user_message.strip())

    if intent is None:
        logger.debug(
            f"Rule engine: no intent matched for: {user_message[:60]}")
        return None

    template = RESPONSES.get(intent)
    if not template:
        logger.debug(f"Rule engine: intent '{intent}' has no template")
        return None

    lang = "sw" if language == "sw" else "en"
    response = template.get(lang) or template.get("en")

    logger.info(f"Rule engine answered with intent='{intent}' lang='{lang}'")
    return response


def get_all_intents() -> list:
    """Return list of all supported intent keys (for testing/debugging)."""
    return list(RESPONSES.keys())
