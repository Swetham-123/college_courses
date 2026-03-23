#!/usr/bin/env python3
"""
UNIVERSITY COURSE SCRAPER v7
Output: level (UG/PG/Diploma/PhD), program (B.Tech./MBA/etc.), name (specialization only)

INSTALL:  pip install requests beautifulsoup4 pandas openpyxl lxml
RUN:
  python scraper.py                      # all 700
  python scraper.py --start 0 --end 50  # rows 0-49
  python scraper.py --resume            # skip already done
  python scraper.py --row 0            # test one university
  python scraper.py --workers 6        # 6 parallel workers
"""

import os, re, sys, csv, json, time, logging, argparse, warnings
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
import pandas as pd
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore")

# =============================================================================
# CONFIG
# =============================================================================
EXCEL_FILE   = "University_Part2_rows700_1399.xlsx"
OUTPUT_DIR   = "university_courses"
LOG_CSV      = "scraping_log.csv"
NUM_WORKERS  = 4
DELAY_PAGE   = 0.4
TIMEOUT      = 12
MAX_RETRIES  = 2
MAX_SUBPAGES = 20

# =============================================================================
# ROTATING USER AGENTS
# =============================================================================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
]
_ua_idx  = 0
_ua_lock = threading.Lock()

def next_ua():
    global _ua_idx
    with _ua_lock:
        ua = USER_AGENTS[_ua_idx % len(USER_AGENTS)]
        _ua_idx += 1
        return ua

# =============================================================================
# LOGGING
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("scraper.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log       = logging.getLogger(__name__)
_log_lock = threading.Lock()


# =============================================================================
# DEGREE PROGRAM TABLE
# Each entry: (regex_pattern, canonical_program_code, level)
# More specific patterns must come FIRST
# =============================================================================
PROGRAM_TABLE = [
    # PhD
    (r"Ph\.?\s*D\.?|Doctor\s+of\s+Philosophy|Doctoral",    "Ph.D.",       "PhD"),
    (r"D\.?\s*Litt\.?|D\.?\s*Sc\b",                        "D.Sc.",       "PhD"),
    # Integrated (5-year dual)
    (r"B\.?\s*Tech\.?\s*\+\s*M\.?\s*Tech",                 "B.Tech.+M.Tech.", "Integrated"),
    (r"B\.?\s*A\.?\s*[+&]\s*L\.?\s*L\.?\s*B",              "BA LLB",      "Integrated"),
    (r"B\.?\s*B\.?\s*A\.?\s*[+&]\s*L\.?\s*L\.?\s*B",       "BBA LLB",     "Integrated"),
    (r"B\.?\s*Com\.?\s*[+&]\s*L\.?\s*L\.?\s*B",            "B.Com. LLB",  "Integrated"),
    (r"B\.?\s*Sc\.?\s*[,&+]\s*M\.?\s*Sc",                  "B.Sc.+M.Sc.", "Integrated"),
    (r"5\s*-\s*[Yy]ear\s+Integrated",                      "Integrated",  "Integrated"),
    (r"Integrated\s+[A-Z]",                                 "Integrated",  "Integrated"),
    (r"Dual\s*Degree",                                      "Dual Degree", "Integrated"),
    # PG Medical
    (r"M\.?\s*D\b",                                         "M.D.",        "PG"),
    (r"M\.?\s*Ch\b",                                        "M.Ch.",       "PG"),
    (r"D\.?\s*M\b",                                         "D.M.",        "PG"),
    (r"MDS\b",                                              "MDS",         "PG"),
    (r"M\.?\s*V\.?\s*Sc\b",                                 "M.V.Sc.",     "PG"),
    # PG Engineering
    (r"M\.?\s*Tech\b",                                      "M.Tech.",     "PG"),
    (r"M\.?\s*E\b",                                         "M.E.",        "PG"),
    (r"M\.?\s*Arch\b",                                      "M.Arch.",     "PG"),
    (r"M\.?\s*Plan\b",                                      "M.Plan.",     "PG"),
    (r"M\.?\s*Des\b",                                       "M.Des.",      "PG"),
    # PG Science
    (r"M\.?\s*Sc\b",                                        "M.Sc.",       "PG"),
    (r"M\.?\s*C\.?\s*A\b",                                  "MCA",         "PG"),
    # PG Arts / Humanities
    (r"M\.?\s*S\.?\s*W\b",                                  "M.S.W.",      "PG"),
    (r"M\.?\s*A\b",                                         "M.A.",        "PG"),
    # PG Commerce / Management
    (r"M\.?\s*B\.?\s*A\b|MBA\b",                            "MBA",         "PG"),
    (r"M\.?\s*Com\b",                                       "M.Com.",      "PG"),
    # PG Pharmacy
    (r"M\.?\s*Pharm\b",                                     "M.Pharm.",    "PG"),
    # PG Other
    (r"M\.?\s*Ed\b",                                        "M.Ed.",       "PG"),
    (r"M\.?\s*P\.?\s*Ed\b",                                 "M.P.Ed.",     "PG"),
    (r"M\.?\s*L\.?\s*I\.?\s*Sc\b|M\.?\s*Lib\b",             "M.Lib.",      "PG"),
    (r"M\.?\s*F\.?\s*A\b",                                  "M.F.A.",      "PG"),
    (r"M\.?\s*H\.?\s*M\b",                                  "M.H.M.",      "PG"),
    (r"M\.?\s*J\.?\s*M\.?\s*C\b",                           "M.J.M.C.",    "PG"),
    (r"M\.?\s*P\.?\s*T\b|MPT\b",                            "MPT",         "PG"),
    (r"M\.?\s*Voc\b",                                       "M.Voc.",      "PG"),
    (r"M\.?\s*S\b",                                         "M.S.",        "PG"),
    (r"L\.?\s*L\.?\s*M\b|LLM\b",                            "LLM",         "PG"),
    (r"Acharya\b",                                          "Acharya",     "PG"),
    # UG Medical
    (r"MBBS\b",                                             "MBBS",        "UG"),
    (r"BDS\b",                                              "BDS",         "UG"),
    (r"BAMS\b",                                             "BAMS",        "UG"),
    (r"BHMS\b",                                             "BHMS",        "UG"),
    (r"BUMS\b",                                             "BUMS",        "UG"),
    (r"BNYS\b",                                             "BNYS",        "UG"),
    (r"B\.?\s*V\.?\s*Sc\b",                                 "B.V.Sc.",     "UG"),
    # UG Engineering
    (r"B\.?\s*Tech\b",                                      "B.Tech.",     "UG"),
    (r"B\.?\s*E\b",                                         "B.E.",        "UG"),
    (r"B\.?\s*Arch\b",                                      "B.Arch.",     "UG"),
    (r"B\.?\s*Plan\b",                                      "B.Plan.",     "UG"),
    (r"B\.?\s*Des\b",                                       "B.Des.",      "UG"),
    # UG Science
    (r"B\.?\s*Sc\b",                                        "B.Sc.",       "UG"),
    (r"B\.?\s*C\.?\s*A\b|BCA\b",                            "BCA",         "UG"),
    (r"B\.?\s*F\.?\s*Sc\b",                                 "B.F.Sc.",     "UG"),
    # UG Arts / Humanities
    (r"B\.?\s*S\.?\s*W\b",                                  "B.S.W.",      "UG"),
    (r"B\.?\s*A\b",                                         "B.A.",        "UG"),
    # UG Commerce / Management
    (r"B\.?\s*B\.?\s*A\b|BBA\b",                            "BBA",         "UG"),
    (r"B\.?\s*Com\b",                                       "B.Com.",      "UG"),
    # UG Pharmacy / Allied Health
    (r"B\.?\s*Pharm\b|B\.?\s*Pharma\b",                     "B.Pharm.",    "UG"),
    (r"Pharm\.?\s*D\b",                                     "Pharm.D.",    "UG"),
    (r"B\.?\s*P\.?\s*T\b|BPT\b",                            "BPT",         "UG"),
    (r"B\.?\s*M\.?\s*L\.?\s*T\b|BMLT\b",                    "BMLT",        "UG"),
    (r"B\.?\s*O\.?\s*T\b|BOT\b",                            "BOT",         "UG"),
    (r"BASLP\b",                                            "BASLP",       "UG"),
    (r"B\.?\s*Sc\.?\s*Nurs",                                "B.Sc. Nursing","UG"),
    # UG Law
    (r"L\.?\s*L\.?\s*B\b|LLB\b",                            "LLB",         "UG"),
    # UG Education / Sports / Library / Arts
    (r"B\.?\s*Ed\b",                                        "B.Ed.",       "UG"),
    (r"B\.?\s*P\.?\s*Ed\b",                                 "B.P.Ed.",     "UG"),
    (r"D\.?\s*El\.?\s*Ed\b|B\.?\s*El\.?\s*Ed\b",             "D.El.Ed.",    "UG"),
    (r"B\.?\s*L\.?\s*I\.?\s*Sc\b|B\.?\s*Lib\b",              "B.Lib.",      "UG"),
    (r"B\.?\s*F\.?\s*A\b",                                  "B.F.A.",      "UG"),
    (r"B\.?\s*H\.?\s*M\b",                                  "B.H.M.",      "UG"),
    (r"B\.?\s*J\.?\s*M\.?\s*C\b",                           "B.J.M.C.",    "UG"),
    (r"B\.?\s*Voc\b",                                       "B.Voc.",      "UG"),
    (r"Shastri\b",                                          "Shastri",     "UG"),
    # Diploma / Certificate
    (r"GNM\b",                                              "GNM",         "Diploma"),
    (r"ANM\b",                                              "ANM",         "Diploma"),
    (r"D\.?\s*Pharm\b",                                     "D.Pharm.",    "Diploma"),
    (r"PG\s*Diploma|Post\s*Graduate\s*Diploma",             "PG Diploma",  "Diploma"),
    (r"PGDCA\b",                                            "PGDCA",       "Diploma"),
    (r"Diploma\b",                                          "Diploma",     "Diploma"),
    (r"Certificate\b",                                      "Certificate", "Certificate"),
    # Fallback
    (r"Bachelor\s+of\b",                                    "Bachelor",    "UG"),
    (r"Master\s+of\b",                                      "Master",      "PG"),
]

# Compile all patterns (with word boundaries)
PROGRAM_TABLE_RE = [
    (re.compile(r"\b" + pat + r"\b", re.IGNORECASE), prog, level)
    for pat, prog, level in PROGRAM_TABLE
]


def find_program(text):
    """Find first degree code in text. Returns (prog, level, start, end) or None."""
    for pat, prog, level in PROGRAM_TABLE_RE:
        m = pat.search(text)
        if m:
            return prog, level, m.start(), m.end()
    return None


# =============================================================================
# GARBAGE FILTER  - reject text that is NOT a course name
# =============================================================================
MONTHS_PAT = (r"january|february|march|april|may|june|july|august|"
              r"september|october|november|december")

GARBAGE_RE = re.compile(
    r"^\s*(" + MONTHS_PAT + r")\s+\d{1,2}[,\s]+\d{4}"     # date: March 19, 2026
    r"|^\s*\d{1,2}\s+(" + MONTHS_PAT + r")\s+\d{4}"        # 19 March 2026
    r"|^\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s*$"              # 19/03/2026
    r"|\d+\s*(seats?|intake)"                               # 120 seats
    r"|\d+\s*year[s]?\s+with\s+\d+\s*sem"                   # 3 years with 6 semesters
    r"|with\s+\d+\s*%"                                      # with 45%
    r"|\d+\s*%\s*marks"                                     # 45% marks
    r"|10\+2\+\d|10th\s+pass|12th\s+pass"                   # eligibility patterns
    r"|graduation.*%|graduation.*pattern"
    r"|is\s+(a|an|the)\b.*(year|program|course|curriculum)" # descriptions
    r"|is\s+abbreviated\s+as|refers\s+to|also\s+known"
    r"|curriculum\s+with\s+both|yearly\s+and\s+semester"
    r"|^\s*(to\s|be\s|for\s|the\s|this\s|these\s|those\s"
    r"|congratulations|academic\s+calendar|click\s+here"
    r"|read\s+more|apply\s+now|admission\s+open"
    r"|fee\s+structure|scholarship|enquire|download\s"
    r"|student\s+representative|nominated\s+by"
    r"|to\s+be\s+nominated|ex.?officio"
    r"|workshop\s+on|seminar\s+on|certificate\s+will\s+be"
    r"|can\s+be\s+pursued|diploma/degree\s+can"
    r"|further\s+diploma\s|you\s+will\s+be"
    r"|be\s+the\s+best|po\d+\s)",
    re.IGNORECASE,
)

GARBAGE_EXACT = re.compile(
    r"^(diploma\s+courses?\b|ug\s+courses?|pg\s+courses?"
    r"|graduate\s+courses?|postgraduate\s+courses?"
    r"|certificate\s+courses?|courses?\s+offered"
    r"|programmes?\s+offered|home|about|contact"
    r"|gallery|news|events|login|logout|register"
    r"|search|sitemap|careers|alumni|feedback)\s*",
    re.IGNORECASE,
)

PERSON_NAME_RE = re.compile(
    r"^\s*(mr\.|mrs\.|ms\.|dr\.|prof\.|shri\s|smt\.|er\.)\s+[A-Z]",
    re.IGNORECASE,
)


def is_garbage(text):
    t = text.strip()
    if not t or len(t) < 2:
        return True
    if re.match(r"^[\d\s.,;:\-()\[\]/\\]+$", t):
        return True
    if GARBAGE_RE.search(t):
        return True
    if GARBAGE_EXACT.match(t):
        return True
    if PERSON_NAME_RE.match(t):
        return True
    return False


# =============================================================================
# SPECIALIZATION EXTRACTOR
# =============================================================================
HONS_RE = re.compile(
    r"\s*\(\s*(hons?\.?|honours?|lateral|part.?time|full.?time|[0-9]+\s*year)\s*\)\s*",
    re.IGNORECASE,
)

SPEC_END_RE = re.compile(
    r"\s*\d+\s*(year|yr|seats?|credit|intake|semester)"
    r"|\s*(fee[s]?|eligibility|admission|apply|click|read"
    r"|download|register|contact|duration|part.time|distance|regular)\b",
    re.IGNORECASE,
)

# Reject specializations that start with noise words
SPEC_BAD_START = re.compile(
    r"^(courses?|programmes?|programs?|studies|offered|at\s|by\s|from\s"
    r"|for\s|the\s|in\s+the|department|university|college|institute)\b",
    re.IGNORECASE,
)


def extract_spec(text, prog_end):
    """Extract clean specialization name from text after degree code ends."""
    after = text[prog_end:].strip()
    if not after:
        return ""
    # Remove (Hons.), (Lateral) etc.
    after = HONS_RE.sub(" ", after).strip()
    # Strip leading separator punctuation only (not letters)
    after = re.sub(r"^[\s\-:.()\[\],]+", "", after).strip()
    # Strip leading prepositions
    after = re.sub(r"^(in|of|for|the)\s+", "", after, flags=re.I).strip()
    # Stop at noise markers
    m = SPEC_END_RE.search(after)
    if m:
        after = after[:m.start()].strip()
    after = after[:80]
    # Clean unbalanced parentheses
    after = re.sub(r"\s*\([^)]*$", "", after).strip()   # trailing unclosed (
    after = re.sub(r"^[A-Za-z.]+\)", "", after).strip()  # leading word)
    after = after.strip(" .,;:-")
    if not after or len(after) < 2 or re.match(r"^\d+$", after):
        return ""
    # Reject if spec starts with noise words
    if SPEC_BAD_START.match(after):
        return ""
    # Reject if the spec IS another degree code
    if find_program(after) and find_program(after)[2] == 0:
        return ""
    return after


# =============================================================================
# SPECIALIZATION NORMALISER  - expand abbreviations
# =============================================================================
_ABBREVS = [
    (r"^aiml$",               "Artificial Intelligence & Machine Learning"),
    (r"^ai\s*[&]\s*ml$",      "Artificial Intelligence & Machine Learning"),
    (r"^ai$",                 "Artificial Intelligence"),
    (r"^ml$",                 "Machine Learning"),
    (r"^cse$",                "Computer Science & Engineering"),
    (r"^ece$",                "Electronics & Communication Engineering"),
    (r"^eee$",                "Electrical & Electronics Engineering"),
    (r"^ee$",                 "Electrical Engineering"),
    (r"^me$",                 "Mechanical Engineering"),
    (r"^ce$",                 "Civil Engineering"),
    (r"^it$",                 "Information Technology"),
    (r"^ds$",                 "Data Science"),
    (r"^iot$",                "Internet of Things"),
    (r"^vlsi$",               "VLSI Design"),
    (r"^hr$",                 "Human Resource Management"),
    (r"^ib$",                 "International Business"),
    (r"^fin$",                "Finance"),
    (r"^mkt$",                "Marketing"),
    (r"^scm$",                "Supply Chain Management"),
    (r"^ba$",                 "Business Analytics"),
]
_ABBREVS_RE = [(re.compile(p, re.I), v) for p, v in _ABBREVS]


def normalise_spec(text):
    t = text.strip()
    if not t:
        return t
    # "CSE (something)" -> "Computer Science & Engineering (something)"
    m = re.match(r"^cse\s*(\(.+\))?$", t, re.I)
    if m:
        suffix = (" " + m.group(1)) if m.group(1) else ""
        return "Computer Science & Engineering" + suffix
    for pat, exp in _ABBREVS_RE:
        if pat.match(t):
            return exp
    return t


# =============================================================================
# LINE PARSER  -> list of {level, program, name}
# =============================================================================
def parse_line(text):
    """
    Parse one line of text.
    Returns list of clean {level, program, name} dicts.
    Each entry has ONLY these 3 fields — nothing else.
    """
    text = re.sub(r"\s+", " ", str(text)).strip()
    if not text or is_garbage(text):
        return []

    results = []
    seen    = set()
    pos     = 0

    while pos < len(text):
        match = find_program(text[pos:])
        if not match:
            break

        prog, level, rel_start, rel_end = match
        abs_end = pos + rel_end

        spec = extract_spec(text, abs_end)
        spec = normalise_spec(spec)
        name = spec if spec else prog

        key = (prog.lower(), name.lower())
        if key not in seen:
            seen.add(key)
            results.append({"level": level, "program": prog, "name": name})

        pos = abs_end
        if not spec:
            break   # standalone degree (MBBS, GNM etc) - stop here

    return results


# =============================================================================
# HTML EXTRACTION STRATEGIES
# =============================================================================
def _add_unique(results, seen, items):
    for p in items:
        k = (p["program"].lower(), p["name"].lower())
        if k not in seen:
            seen.add(k)
            results.append(p)


def parse_table(table):
    results, seen = [], set()
    rows = table.find_all("tr")
    if not rows:
        return results

    hdrs = [re.sub(r"\s+", " ", c.get_text()).strip().lower()
            for c in rows[0].find_all(["th", "td"])]

    col_lv = col_nm = col_pr = None
    for i, h in enumerate(hdrs):
        if col_lv is None and any(x in h for x in ["ug/pg","level","type","category"]):
            col_lv = i
        if col_nm is None and any(x in h for x in
                ["name of course","course name","programme name","branch",
                 "specialization","specialisation","name"]):
            col_nm = i
        if col_pr is None and any(x in h for x in
                ["programme","program","degree","qualification","course"]):
            col_pr = i

    has_hdr   = col_nm is not None or col_pr is not None
    data_rows = rows[1:] if has_hdr else rows

    for row in data_rows:
        cells = [re.sub(r"\s+", " ", td.get_text()).strip()
                 for td in row.find_all(["td", "th"])]
        if not cells or all(not c for c in cells):
            continue

        lv_hint = name_raw = ""
        if has_hdr:
            if col_lv is not None and col_lv < len(cells):
                lv_hint = cells[col_lv]
            if col_nm is not None and col_nm < len(cells):
                name_raw = cells[col_nm]
            elif col_pr is not None and col_pr < len(cells):
                name_raw = cells[col_pr]
        else:
            for cell in cells:
                if parse_line(cell):
                    name_raw = cell; break

        if not name_raw:
            continue

        for p in parse_line(name_raw):
            if lv_hint:
                lh = lv_hint.lower()
                if   "ug" in lh or "under" in lh:   p["level"] = "UG"
                elif "pg" in lh or "post" in lh:    p["level"] = "PG"
                elif "diploma" in lh:                p["level"] = "Diploma"
                elif "phd" in lh or "ph.d" in lh:   p["level"] = "PhD"
            _add_unique(results, seen, [p])

    return results


def parse_lists(soup):
    results, seen = [], set()
    for ul in soup.find_all(["ul", "ol"]):
        for li in ul.find_all("li"):
            t = re.sub(r"\s+", " ", li.get_text()).strip()
            _add_unique(results, seen, parse_line(t))
    return results


def parse_accordions(soup):
    results, seen = [], set()
    CLS = re.compile(
        r"accordion|collapse|tab.?pane|tab.?content|card.?body|"
        r"panel.?body|course.?list|programme.?list|program.?list|"
        r"course.?item|course.?content|degree.?list", re.IGNORECASE)
    for div in soup.find_all(["div", "section"], class_=True):
        if not CLS.search(" ".join(div.get("class", []))):
            continue
        for line in div.get_text(separator="\n").split("\n"):
            _add_unique(results, seen, parse_line(re.sub(r"\s+", " ", line).strip()))
    return results


def parse_under_headings(soup):
    results, seen = [], set()
    KW = ["course","programme","program","offered","degree","academic",
          "ug","pg","diploma","certificate","doctoral"]
    for h in soup.find_all(["h1","h2","h3","h4","h5","h6"]):
        if not any(kw in h.get_text(strip=True).lower() for kw in KW):
            continue
        sib, d = h.find_next_sibling(), 0
        while sib and d < 10:
            if getattr(sib, "name", "") in ("h1","h2","h3","h4","h5","h6"):
                break
            for line in sib.get_text(separator="\n").split("\n"):
                _add_unique(results, seen, parse_line(re.sub(r"\s+", " ", line).strip()))
            sib = sib.find_next_sibling()
            d  += 1
    return results


def parse_fulltext(soup):
    results, seen = [], set()
    for tag in soup(["script","style","noscript","nav","footer",
                     "header","form","button","meta","link"]):
        tag.decompose()
    for line in soup.get_text(separator="\n").split("\n"):
        _add_unique(results, seen, parse_line(re.sub(r"\s+", " ", line).strip()))
    return results


def extract_all(soup):
    seen, result = set(), []

    def add(items):
        for item in items:
            k = (item["program"].lower(), item["name"].lower())
            if k not in seen:
                seen.add(k); result.append(item)

    for table in soup.find_all("table"):
        add(parse_table(table))
    add(parse_accordions(soup))
    add(parse_lists(soup))
    add(parse_under_headings(soup))
    if len(result) < 5:
        add(parse_fulltext(soup))
    return result


# =============================================================================
# COLLEGE GROUPING
# =============================================================================
COLLEGE_PREFIX = [
    "school of","faculty of","department of","institute of",
    "college of","centre of","center of","division of","dept of",
]
COLLEGE_WORDS = [
    "engineering","management","law","science","arts","pharmacy",
    "nursing","agriculture","medical","medicine","commerce",
    "education","technology","architecture","design","hotel",
    "hospital","journalism","library","social work","computer",
    "business","humanities","paramedical","ayurveda","dental",
    "veterinary","fisheries","dairy","forestry","horticulture",
    "biotechnology","information technology",
]


def is_college_heading(text):
    t = text.lower().strip()
    if not t or len(t) > 100:
        return False
    return any(t.startswith(kw) for kw in COLLEGE_PREFIX) or \
           any(kw in t for kw in COLLEGE_WORDS)


def group_into_colleges(soup, flat_programs, univ_name):
    colleges, seen_prog = [], set()

    for h in soup.find_all(["h1","h2","h3","h4","h5"]):
        ht = re.sub(r"\s+", " ", h.get_text()).strip()
        if not is_college_heading(ht):
            continue
        local, sib, depth = [], h.find_next_sibling(), 0
        while sib and depth < 20:
            if getattr(sib, "name", "") in ("h1","h2","h3","h4","h5"):
                if is_college_heading(re.sub(r"\s+", " ", sib.get_text()).strip()):
                    break
            items = []
            for tbl in (sib.find_all("table") if hasattr(sib, "find_all") else []):
                items.extend(parse_table(tbl))
            for li in (sib.find_all("li") if hasattr(sib, "find_all") else []):
                items.extend(parse_line(re.sub(r"\s+", " ", li.get_text()).strip()))
            if hasattr(sib, "get_text"):
                for line in sib.get_text(separator="\n").split("\n"):
                    items.extend(parse_line(re.sub(r"\s+", " ", line).strip()))
            for p in items:
                k = (p["program"].lower(), p["name"].lower())
                if k not in seen_prog:
                    seen_prog.add(k); local.append(p)
            sib = sib.find_next_sibling()
            depth += 1
        if local:
            colleges.append({"college_name": ht, "programs": local})

    if len(colleges) >= 2:
        return colleges
    if len(colleges) == 1 and len(colleges[0]["programs"]) >= 3:
        return colleges
    if flat_programs:
        return [{"college_name": univ_name, "programs": flat_programs}]
    return []


def merge_colleges(existing, new_colleges):
    index = {c["college_name"].lower(): i for i, c in enumerate(existing)}
    for nc in new_colleges:
        key = nc["college_name"].lower()
        if key in index:
            eks = {(p["program"].lower(), p["name"].lower())
                   for p in existing[index[key]]["programs"]}
            for p in nc["programs"]:
                k = (p["program"].lower(), p["name"].lower())
                if k not in eks:
                    existing[index[key]]["programs"].append(p); eks.add(k)
        else:
            existing.append(nc); index[key] = len(existing) - 1
    return existing


# =============================================================================
# HTTP LAYER
# =============================================================================
def normalize_url(raw):
    if not raw or str(raw).strip().lower() in ("nan","none","n/a","-",""):
        return None
    url = str(raw).strip().rstrip("/")
    if not url.startswith(("http://","https://")):
        url = "https://" + url
    return url


def same_domain(url, base):
    try:
        return urlparse(url).netloc.lstrip("www.") == urlparse(base).netloc.lstrip("www.")
    except Exception:
        return False


def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": next_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
    })
    return s


def fetch(url, session, retries=MAX_RETRIES):
    variants = [url]
    if url.startswith("https://"):
        variants.append(url.replace("https://","http://",1))
    else:
        variants.append(url.replace("http://","https://",1))
    if not urlparse(url).netloc.startswith("www."):
        variants.append(url.replace("://","://www.",1))
    for u in variants:
        for attempt in range(retries + 1):
            try:
                if attempt > 0:
                    session.headers["User-Agent"] = next_ua()
                r = session.get(u, timeout=TIMEOUT, allow_redirects=True, verify=False)
                r.raise_for_status()
                return r, r.url
            except requests.exceptions.TooManyRedirects:
                return None, None
            except requests.exceptions.HTTPError as e:
                code = e.response.status_code
                if code in (403, 406):
                    session.headers["User-Agent"] = next_ua(); time.sleep(1.5)
                elif code in (404, 410):
                    break
                elif code == 429:
                    time.sleep(5)
                if attempt < retries:
                    time.sleep(1)
            except Exception:
                if attempt < retries:
                    time.sleep(1)
    return None, None


# =============================================================================
# LINK DISCOVERY
# =============================================================================
COURSE_LINK_KW = [
    "courses offered","programmes offered","programs offered",
    "academic programs","academic programmes",
    "all courses","all programmes","all programs",
    "ug courses","pg courses","ug & pg","ug and pg",
    "undergraduate","postgraduate","diploma courses",
    "courses","programmes","programs","academics",
    "departments","schools","faculties","course list",
    "study programs","what we offer","our programs",
]
COURSE_URL_KW = ["course","programme","program","academ","department",
                  "faculty","school","offered","ugpg","ug-pg","degree"]
COMMON_PATHS  = [
    "/courses-offered","/courses_offered","/CoursesOffered",
    "/courses","/courses.php","/courses.aspx","/courses.html",
    "/programmes-offered","/programmes","/programmes.php",
    "/programs-offered","/programs","/programs.php",
    "/academic-programs","/academic-programmes",
    "/academics/courses","/academics/programmes","/academics",
    "/academics.php","/ugpg-courses","/ug-pg-courses",
    "/ug-courses","/pg-courses","/departments","/schools",
    "/faculties","/graduate-courses","/postgraduate-courses",
    "/allprogramme.php","/Programme.aspx","/Programmes.aspx",
    "/coursesoffered.php","/our-courses","/undergraduate",
    "/postgraduate","/program-list","/degree-programs",
    "/school-of-engineering","/school-of-management",
    "/school-of-law","/school-of-science",
]


def discover_links(soup, base_url):
    candidates = {}

    def add(url, score):
        candidates[url] = max(candidates.get(url, 0), score)

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#","mailto:","tel:","javascript:","data:")):
            continue
        full = urljoin(base_url, href)
        if not same_domain(full, base_url):
            continue
        text  = a.get_text(" ", strip=True).lower()
        path  = urlparse(full).path.lower()
        score = 0
        for kw in COURSE_LINK_KW:
            if text == kw:    score += 15; break
            elif kw in text:  score += 8;  break
        for kw in COURSE_URL_KW:
            if kw in path:    score += 4;  break
        if "offered"   in text or "offered"   in path: score += 5
        if "all"       in text:                         score += 2
        if "ug"        in text or "pg"        in text:  score += 3
        if "diploma"   in text:                         score += 2
        if "phd"       in text or "doctoral"  in text:  score += 2
        if "admission" in text and "course" not in text: score -= 3
        if score > 0:
            add(full, score)

    for path in COMMON_PATHS:
        u = base_url.rstrip("/") + path
        if u not in candidates:
            candidates[u] = 1

    return sorted(candidates.items(), key=lambda x: -x[1])


# =============================================================================
# SCRAPE ONE UNIVERSITY
# =============================================================================
def scrape_one(row):
    aishe   = str(row.get("Aishe Code","")).strip()
    name    = str(row.get("Name","")).strip()
    state   = str(row.get("State","")).strip()
    raw_url = row.get("Website","")
    website = normalize_url(raw_url)

    result = {
        "aishe_code": aishe,
        "university": name,
        "state":      state,
        "website":    str(raw_url).strip(),
        "colleges":   [],
    }

    if not website:
        result["status"] = "no_website"; return result

    session = make_session()
    log.info(f"  [{aishe}] GET {website}")
    resp, final_url = fetch(website, session)

    if resp is None:
        result["status"] = "unreachable"
        log.warning(f"  [{aishe}] Unreachable")
        return result

    base_url   = final_url.rstrip("/")
    soup_home  = BeautifulSoup(resp.text, "lxml")
    candidates = discover_links(soup_home, base_url)
    all_coll   = []
    visited    = {base_url}
    tried      = 0

    flat = extract_all(soup_home)
    if flat:
        grouped = group_into_colleges(soup_home, flat, name)
        if grouped:
            all_coll = merge_colleges(all_coll, grouped)
            n = sum(len(c["programs"]) for c in all_coll)
            log.info(f"  [{aishe}] Homepage -> {n} programs")

    for url, score in candidates:
        if tried >= MAX_SUBPAGES: break
        if url in visited:        continue
        visited.add(url); time.sleep(DELAY_PAGE)
        sub_resp, sub_url = fetch(url, session)
        tried += 1
        if sub_resp is None: continue

        sub_soup = BeautifulSoup(sub_resp.text, "lxml")
        sub_flat = extract_all(sub_soup)
        if sub_flat:
            sub_grp = group_into_colleges(sub_soup, sub_flat, name)
            if sub_grp:
                n_before = sum(len(c["programs"]) for c in all_coll)
                all_coll = merge_colleges(all_coll, sub_grp)
                n_after  = sum(len(c["programs"]) for c in all_coll)
                if n_after > n_before:
                    log.info(f"  [{aishe}] [s={score}] +{n_after-n_before} from {url}")
                if tried < MAX_SUBPAGES:
                    for mu, ms in discover_links(sub_soup, base_url):
                        if mu not in visited and ms >= 5:
                            candidates.append((mu, ms - 1))

        if sum(len(c["programs"]) for c in all_coll) >= 30 and score < 4:
            break

    result["colleges"] = all_coll
    total = sum(len(c["programs"]) for c in all_coll)
    log.info(f"  [{aishe}] DONE -> {total} programs in {len(all_coll)} groups")
    return result


# =============================================================================
# HELPERS & MAIN
# =============================================================================
def safe_filename(aishe, name):
    safe = re.sub(r"[^\w\s-]", "", name)
    safe = re.sub(r"\s+", "_", safe.strip())
    return f"{aishe}_{safe[:60]}.json"


def save_json(data, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description="University Course Scraper v7")
    parser.add_argument("--excel",   default=EXCEL_FILE)
    parser.add_argument("--start",   type=int, default=0)
    parser.add_argument("--end",     type=int, default=None)
    parser.add_argument("--row",     type=int, default=None)
    parser.add_argument("--resume",  action="store_true")
    parser.add_argument("--workers", type=int, default=NUM_WORKERS)
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    import urllib3; urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    log.info(f"Loading {args.excel}")
    df = pd.read_excel(args.excel)

    if args.row is not None:
        subset = df.iloc[args.row: args.row + 1]
    else:
        end    = args.end or len(df)
        subset = df.iloc[args.start:end]

    total   = len(subset)
    workers = min(args.workers, total)
    log.info(f"Processing {total} universities | {workers} workers")

    log_rows  = []
    t0        = datetime.now()
    completed = 0

    def process(item):
        idx, row = item
        aishe = str(row.get("Aishe Code","")).strip()
        uname = str(row.get("Name","")).strip()
        fname = safe_filename(aishe, uname)
        fpath = os.path.join(OUTPUT_DIR, fname)
        if args.resume and os.path.exists(fpath):
            with open(fpath, encoding="utf-8") as f:
                return idx, row, json.load(f), fname
        try:
            data = scrape_one(row)
        except Exception as e:
            log.error(f"CRASH [{aishe}]: {e}", exc_info=True)
            data = {"aishe_code":aishe,"university":uname,
                    "state":str(row.get("State","")),"website":str(row.get("Website","")),
                    "status":"error","error":str(e),"colleges":[]}
        save_json(data, fpath)
        return idx, row, data, fname

    rows_list = list(subset.iterrows())
    with ThreadPoolExecutor(max_workers=workers) as exe:
        futures = {exe.submit(process, r): r for r in rows_list}
        for future in as_completed(futures):
            completed += 1
            try:
                idx, row, data, fname = future.result()
            except Exception as e:
                log.error(f"Future error: {e}"); continue
            uname  = str(row.get("Name","")).strip()
            n_prog = sum(len(c["programs"]) for c in data.get("colleges",[]))
            log.info(f"[{completed}/{total}] {'OK' if n_prog > 0 else '--'} {uname} -- {n_prog} programs")
            with _log_lock:
                log_rows.append({
                    "row": idx,
                    "aishe_code": str(row.get("Aishe Code","")).strip(),
     git                "name": uname,
                    "website": str(row.get("Website","")),
                    "programs": n_prog,
                    "file": fname,
                })
                with open(LOG_CSV, "w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=log_rows[0].keys())
                    w.writeheader(); w.writerows(log_rows)

    elapsed   = str(datetime.now() - t0).split(".")[0]
    with_data = sum(1 for r in log_rows if r["programs"] > 0)
    print(f"\nDONE: {total} universities | {with_data} with data | {elapsed}")
    print(f"Output: {OUTPUT_DIR}/   Log: {LOG_CSV}")


if __name__ == "__main__":
    main()