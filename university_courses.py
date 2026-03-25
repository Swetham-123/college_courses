"""
University Course Scraper v3  —  4-Pattern Aware
=================================================

Handles ALL 4 university website patterns:

  PATTERN 1 — Standard nav / static pages
    • requests + BeautifulSoup
    • Follows internal links containing academic/course keywords
    • Extracts degree + course from tables, lists, paragraphs

  PATTERN 2 — Direct /courses or /programmes URL  (e.g. magadhuniversity.ac.in)
    • Tries common course-page slugs: /courses /programmes /academic /programs
    • Selenium: scrolls full page, expands accordions, clicks tabs
    • Paginates through all pages of the listing

  PATTERN 3 — JS SPA with aca-pro-box sections  (e.g. nitw.ac.in)
    • Selenium renders the JS app
    • Finds <div class="aca-pro-box"> blocks → reads the h2 (degree level) + links
    • Follows every c-link href and scrapes that sub-page too

  PATTERN 4 — Academics → Courses Offered → each course → specialisations  (e.g. nims.edu.in)
    • Selenium: clicks "Academics" nav item
    • Finds "Courses Offered" link → opens it
    • Iterates every course card / row → clicks into it
    • Extracts specialisations / electives listed inside

Requirements:
    pip install requests beautifulsoup4 openpyxl lxml selenium webdriver-manager

Usage:
    python university_scraper_v3.py               # all 700
    python university_scraper_v3.py --limit 10    # test first 10
    python university_scraper_v3.py --resume      # skip already done
    python university_scraper_v3.py --workers 3   # parallel Chrome instances
    python university_scraper_v3.py --no-selenium # static only (faster)
"""

import re, os, sys, json, time, logging, argparse
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
import openpyxl

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

EXCEL_FILE         = "University_Part2_rows700_1399.xlsx"
OUTPUT_DIR         = "output"
LOG_FILE           = "scraper_v3.log"

REQUEST_TIMEOUT    = 8       # OPTIMIZED: was 20 (2.5x faster)
PAGE_LOAD_TIMEOUT  = 12      # OPTIMIZED: was 35 (3x faster)
JS_SETTLE_WAIT     = 1       # OPTIMIZED: was 4 seconds after JS navigation (4x faster)
CLICK_WAIT         = 0.3     # OPTIMIZED: was 1.5 seconds after each click (5x faster)
MAX_PAGES          = 25      # max pages visited per university (increased for completeness)
MAX_PAGINATION     = 15      # max "Next" clicks per table (increased for completeness)
MAX_COURSE_CLICKS  = 80      # max individual course links to follow (Pattern 4)
MAX_WORKERS        = 5       # OPTIMIZED: was 3 parallel browser instances (67% more parallelization)
RETRY_COUNT        = 1       # OPTIMIZED: was 2 (fail fast)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}

# Common slug paths that universities use for course listings (Pattern 2)
COURSE_SLUG_PATHS = [
    "/courses", "/programmes", "/programs", "/academic-programmes",
    "/academic-programs", "/academic", "/academics", "/academics/programmes",
    "/ug-programmes", "/pg-programmes", "/phd-programme",
    "/admissions/courses", "/admissions/programmes",
    "/department/courses", "/departments",
    "/schools", "/faculties",
    "/study-programmes", "/offered-courses",
]

COURSE_NAV_KEYWORDS = [
    "programme", "program", "course", "academic", "department",
    "admission", "curriculum", "school of", "faculty of", "degree",
    "undergraduate", "postgraduate", "ug", "pg", "phd", "doctoral",
    "offered", "study", "stream", "discipline", "specialisation",
    "specialization",
]

# ══════════════════════════════════════════════════════════════════════════════
# DEGREE / LEVEL DETECTION
# ══════════════════════════════════════════════════════════════════════════════

LEVEL_MAP = {
    "ph.d": "Doctoral",      "phd": "Doctoral",        "d.sc": "Doctoral",
    "d.litt": "Doctoral",    "fellow": "Doctoral",
    "m.tech": "Postgraduate","mtech": "Postgraduate",   "m.e.": "Postgraduate",
    "m.sc":  "Postgraduate", "msc":  "Postgraduate",    "m.a.": "Postgraduate",
    "m.com": "Postgraduate", "mcom": "Postgraduate",    "mba":  "Postgraduate",
    "m.b.a":"Postgraduate",  "mca":  "Postgraduate",    "m.c.a":"Postgraduate",
    "m.ed":  "Postgraduate", "m.pharm":"Postgraduate",  "mpharm":"Postgraduate",
    "m.arch":"Postgraduate", "m.plan":"Postgraduate",   "llm":  "Postgraduate",
    "l.l.m":"Postgraduate",  "pgdm": "Postgraduate",    "pg diploma":"Postgraduate Diploma",
    "post graduate":"Postgraduate",    "postgraduate":"Postgraduate",
    "b.tech":"Undergraduate","btech":"Undergraduate",   "b.e.": "Undergraduate",
    "b.sc": "Undergraduate", "bsc":  "Undergraduate",   "b.a.": "Undergraduate",
    "b.com":"Undergraduate", "bcom": "Undergraduate",   "bba":  "Undergraduate",
    "b.b.a":"Undergraduate", "bca":  "Undergraduate",   "b.c.a":"Undergraduate",
    "b.ed": "Undergraduate", "b.pharm":"Undergraduate", "bpharm":"Undergraduate",
    "b.arch":"Undergraduate","b.plan":"Undergraduate",  "llb":  "Undergraduate",
    "l.l.b":"Undergraduate", "b.des":"Undergraduate",   "bdes": "Undergraduate",
    "mbbs": "Undergraduate", "b.d.s":"Undergraduate",   "bds":  "Undergraduate",
    "under graduate":"Undergraduate",  "undergraduate":"Undergraduate",
    "integrated":"Undergraduate",
    "diploma":"Diploma",     "certificate":"Certificate",
    "advanced diploma":"Diploma",
    "dual degree":"Undergraduate",
    # short UG/PG headers used in aca-pro-box (Pattern 3)
    " ug": "Undergraduate",  " pg": "Postgraduate",
}

DEGREE_RE = re.compile(
    r"""
    \b(
        (?:Integrated\s+)?
        (?:
            Ph\.?D | D\.Sc | D\.Litt
          | M\.?Tech | M\.?E\b | M\.?Sc | M\.?A\b | M\.?Com
          | MBA | MCA | M\.?Ed | M\.?Pharm | M\.?Arch | M\.?Plan
          | LLM | PGDM | PG\s*Diploma
          | B\.?Tech | B\.?E\b | B\.?Sc | B\.?A\b | B\.?Com
          | BBA | BCA | B\.?Ed | B\.?Pharm | B\.?Arch | B\.?Plan
          | LLB | B\.?Des | MBBS | BDS
          | Diploma | Certificate
          | Dual\s+Degree
        )
    )
    [\s\.\-–—]*(?:in|of|In|Of)?[\s\.\-–—]*
    ([\w\s\(\)\-/&,\.]{3,80}?)
    (?=\s*(?:\n|\r|\||\||$|\d\s*[Yy]ear|\d\s*[Ss]em|[A-Z]{2,}))
    """,
    re.VERBOSE | re.IGNORECASE,
)

def detect_level(text: str) -> str:
    tl = " " + text.lower() + " "
    for key, level in LEVEL_MAP.items():
        if key in tl:
            return level
    return "Unknown"

def clean_name(raw: str) -> str:
    raw = raw.strip(" .,;:-–—|/\\\n\r\t")
    raw = re.sub(r"\s{2,}", " ", raw)
    if len(raw) < 3 or sum(c.isalpha() for c in raw) < 3:
        return ""
    return raw

# ══════════════════════════════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def normalize_url(raw: str) -> str:
    raw = raw.strip().rstrip("/")
    if not raw.startswith("http"):
        raw = "https://" + raw
    return raw

def same_domain(url: str, base: str) -> bool:
    bu = urlparse(base).netloc.lstrip("www.")
    cu = urlparse(url).netloc.lstrip("www.")
    return cu == bu or cu.endswith("." + bu) or bu.endswith("." + cu)

def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", "_", name.strip())
    return name[:80]

def strip_noise(soup: BeautifulSoup):
    for tag in soup(["script","style","meta","noscript","footer","header","aside"]):
        tag.decompose()

class CourseCollector:
    """Thread-safe deduplicated course accumulator."""
    def __init__(self):
        self._seen: set[tuple] = set()
        self.courses: list[dict] = []

    def add(self, degree: str, course: str, level: str, source: str):
        degree = degree.strip()
        course = clean_name(course)
        if not course:
            return
        key = (degree.lower()[:60], course.lower()[:60])
        if key in self._seen:
            return
        self._seen.add(key)
        self.courses.append({
            "degree_name": degree,
            "course_name": course,
            "level_of_education": level or detect_level(degree + " " + course),
            "source_url": source,
        })

    def add_from_regex(self, html_or_text: str, source: str):
        for m in DEGREE_RE.finditer(html_or_text):
            deg = m.group(1).strip()
            crs = m.group(2).strip() if m.group(2) else deg
            self.add(deg, crs, detect_level(deg + " " + crs), source)

    def finalize(self) -> list[dict]:
        order = {"Doctoral":0,"Postgraduate":1,"Postgraduate Diploma":2,
                 "Undergraduate":3,"Diploma":4,"Certificate":5,"Unknown":6}
        return sorted(self.courses,
                      key=lambda c: (order.get(c["level_of_education"],9),
                                     c["degree_name"], c["course_name"]))

# ══════════════════════════════════════════════════════════════════════════════
# STATIC FETCH
# ══════════════════════════════════════════════════════════════════════════════

def static_fetch(session: requests.Session, url: str) -> str | None:
    for attempt in range(RETRY_COUNT + 1):
        try:
            r = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT,
                            allow_redirects=True)
            if r.status_code == 200:
                r.encoding = r.apparent_encoding or "utf-8"
                return r.text
            return None
        except requests.exceptions.SSLError:
            try:
                r = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT,
                                allow_redirects=True, verify=False)
                if r.status_code == 200:
                    r.encoding = r.apparent_encoding or "utf-8"
                    return r.text
            except Exception:
                pass
            return None
        except requests.exceptions.ConnectionError:
            if url.startswith("https://") and attempt == 0:
                try:
                    r = session.get("http://" + url[8:], headers=HEADERS,
                                    timeout=REQUEST_TIMEOUT, allow_redirects=True)
                    if r.status_code == 200:
                        r.encoding = r.apparent_encoding or "utf-8"
                        return r.text
                except Exception:
                    pass
            if attempt < RETRY_COUNT:
                time.sleep(1)
        except Exception as e:
            log.debug(f"static_fetch({url}): {e}")
            if attempt < RETRY_COUNT:
                time.sleep(1)
    return None

# ══════════════════════════════════════════════════════════════════════════════
# STATIC HTML EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def extract_from_html(html: str, source_url: str, col: CourseCollector):
    """Extract all courses from a static HTML page into col."""
    soup = BeautifulSoup(html, "lxml")
    strip_noise(soup)

    # 1. Full text regex pass
    full = soup.get_text(separator="\n", strip=True)
    col.add_from_regex(full, source_url)

    # 2. <select> option values
    for sel in soup.find_all("select"):
        nid = (sel.get("name","") + sel.get("id","")).lower()
        if any(k in nid for k in ["course","program","degree","stream","branch"]):
            for opt in sel.find_all("option"):
                txt = opt.get_text(strip=True)
                if len(txt) > 4 and txt.lower() not in ("select","choose","--","all"):
                    col.add_from_regex(txt, source_url)

    # 3. Tables
    for table in soup.find_all("table"):
        hdrs = []
        hr = table.find("tr")
        if hr:
            hdrs = [c.get_text(strip=True).lower() for c in hr.find_all(["th","td"])]
        dcol = next((i for i,h in enumerate(hdrs)
                     if any(k in h for k in ["degree","programme","course","program"])), None)
        for row in table.find_all("tr")[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all(["td","th"])]
            if not cells:
                continue
            txt = cells[dcol] if (dcol is not None and dcol < len(cells)) \
                  else " ".join(cells[:3])
            col.add_from_regex(txt, source_url)

    # 4. Hidden tab/accordion panels
    for div in soup.find_all("div", class_=re.compile(
            r"tab[\-_]?pane|accordion[\-_]?body|collapse|panel[\-_]?body", re.I)):
        col.add_from_regex(div.get_text(separator="\n", strip=True), source_url)

    # 5. Pattern 3 — aca-pro-box (NITW style)
    for box in soup.find_all("div", class_=re.compile(r"aca[\-_]?pro[\-_]?box", re.I)):
        title_el = box.find(["h1","h2","h3","h4"])
        level_label = title_el.get_text(strip=True) if title_el else ""
        level = detect_level(level_label)
        for a in box.find_all("a"):
            cname = a.get_text(strip=True)
            if cname:
                col.add(level_label, cname, level, source_url)


def find_nav_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    seen, cands = set(), []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(strip=True).lower()
        if not href or href.startswith(("#","javascript:","mailto:","tel:")):
            continue
        full = urljoin(base_url, href).split("#")[0].rstrip("/")
        if not same_domain(full, base_url) or full in seen:
            continue
        seen.add(full)
        score = sum(kw in (text + " " + urlparse(full).path.lower())
                    for kw in COURSE_NAV_KEYWORDS)
        if score > 0:
            cands.append((score, full))
    return [u for _, u in sorted(cands, key=lambda x: -x[0])][:MAX_PAGES]


def find_pagination_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    PAG = re.compile(r"(next|»|›|>|\bnext\b)", re.I)
    seen, links = set(), []
    for a in soup.find_all("a", href=True):
        if PAG.search(a.get_text(strip=True)):
            full = urljoin(base_url, a["href"]).split("#")[0]
            if full not in seen and same_domain(full, base_url):
                seen.add(full)
                links.append(full)
    return links

# ══════════════════════════════════════════════════════════════════════════════
# SELENIUM UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def make_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1400,900")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument(f"--user-agent={HEADERS['User-Agent']}")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    return driver


def sel_get(driver, url: str, wait: float = JS_SETTLE_WAIT) -> str | None:
    try:
        driver.get(url)
        time.sleep(wait)
        return driver.page_source
    except Exception as e:
        log.debug(f"sel_get({url}): {e}")
        return None


def sel_click(driver, element, wait: float = CLICK_WAIT):
    from selenium.common.exceptions import ElementClickInterceptedException
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        time.sleep(0.3)
        element.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", element)
    time.sleep(wait)


def sel_find(driver, css: str):
    from selenium.webdriver.common.by import By
    try:
        return driver.find_elements(By.CSS_SELECTOR, css)
    except Exception:
        return []


def sel_find_xpath(driver, xpath: str):
    from selenium.webdriver.common.by import By
    try:
        return driver.find_elements(By.XPATH, xpath)
    except Exception:
        return []

# ══════════════════════════════════════════════════════════════════════════════
# PATTERN 1 — Standard static / nav-based sites
# ══════════════════════════════════════════════════════════════════════════════

def pattern1_static(session: requests.Session, base_url: str,
                    col: CourseCollector, visited: set[str]):
    """Follow nav links statically, paginate, extract."""
    hp = static_fetch(session, base_url)
    if not hp:
        return False
    visited.add(base_url)
    extract_from_html(hp, base_url, col)

    links = find_nav_links(hp, base_url)
    for link in links:
        if link in visited or len(visited) >= MAX_PAGES:
            break
        visited.add(link)
        time.sleep(0.4)
        sub = static_fetch(session, link)
        if not sub:
            continue
        extract_from_html(sub, link, col)
        for pl in find_pagination_links(sub, link)[:MAX_PAGINATION]:
            if pl in visited:
                continue
            visited.add(pl)
            time.sleep(0.3)
            ph = static_fetch(session, pl)
            if ph:
                extract_from_html(ph, pl, col)
    return True

# ══════════════════════════════════════════════════════════════════════════════
# PATTERN 2 — Direct /courses or /programmes page  (Magadh style)
# ══════════════════════════════════════════════════════════════════════════════

def pattern2_courses_page(driver, session: requests.Session,
                          base_url: str, col: CourseCollector, visited: set[str]):
    """
    Try common slug paths. For each one that exists, scrape with Selenium
    (handles JS-rendered course lists, accordions, tabs, pagination).
    """
    parsed = urlparse(base_url)
    domain_root = f"{parsed.scheme}://{parsed.netloc}"

    found_any = False
    for slug in COURSE_SLUG_PATHS:
        url = domain_root + slug
        if url in visited:
            continue

        # Quick static check first
        html = static_fetch(session, url)
        if not html:
            continue

        soup = BeautifulSoup(html, "lxml")
        text_len = len(soup.get_text(strip=True))
        if text_len < 200:
            continue   # redirect/empty page

        visited.add(url)
        found_any = True
        log.debug(f"  Pattern2: found {url}")

        # Selenium render for JS content
        sel_html = sel_get(driver, url)
        working_html = sel_html if sel_html else html
        extract_from_html(working_html, url, col)

        # Expand accordions / tabs on the page
        _expand_page_interactions(driver, url, base_url, col, visited)

        # Paginate
        for _ in range(MAX_PAGINATION):
            next_btns = sel_find_xpath(
                driver,
                "//a[normalize-space()='Next' or normalize-space()='»' "
                "or normalize-space()='›']"
                "|//button[contains(translate(.,'NEXT','next'),'next')]"
            )
            if not next_btns:
                break
            try:
                sel_click(driver, next_btns[0], wait=JS_SETTLE_WAIT)
                extract_from_html(driver.page_source, driver.current_url, col)
            except Exception:
                break

        # Also follow sub-links on this courses page
        links = find_nav_links(working_html, url)
        for link in links[:10]:
            if link in visited:
                continue
            visited.add(link)
            sub = static_fetch(session, link)
            if sub:
                extract_from_html(sub, link, col)

    return found_any


def _expand_page_interactions(driver, current_url: str, base_url: str,
                               col: CourseCollector, visited: set[str]):
    """Click accordions, tabs, dropdowns on the currently loaded page."""
    from selenium.common.exceptions import StaleElementReferenceException

    selectors = [
        ".accordion-button", ".accordion-header button",
        "[data-toggle='collapse']", "[data-bs-toggle='collapse']",
        ".tab-link", ".nav-tabs a", "[role='tab']",
        ".panel-heading a", ".card-header a",
        ".ui-accordion-header", "[aria-expanded='false']",
    ]
    for sel in selectors:
        elems = sel_find(driver, sel)
        for el in elems[:30]:
            try:
                txt = el.text.strip().lower()
                if any(kw in txt for kw in COURSE_NAV_KEYWORDS + ["+"," all"]):
                    sel_click(driver, el, wait=0.8)
                    extract_from_html(driver.page_source, current_url, col)
            except (StaleElementReferenceException, Exception):
                continue

# ══════════════════════════════════════════════════════════════════════════════
# PATTERN 3 — JS SPA with aca-pro-box  (NITW style)
# ══════════════════════════════════════════════════════════════════════════════

def pattern3_aca_pro_box(driver, session: requests.Session,
                         base_url: str, col: CourseCollector, visited: set[str]):
    """
    1. Navigate to /academics or /ap
    2. Find <div class='aca-pro-box'> → h2 = degree level, a.c-link = courses
    3. Follow each c-link and scrape sub-page
    """
    from selenium.webdriver.common.by import By
    from selenium.common.exceptions import StaleElementReferenceException

    parsed = urlparse(base_url)
    root   = f"{parsed.scheme}://{parsed.netloc}"

    # Try candidate academic landing pages
    academic_slugs = ["/academics", "/ap", "/academic-programs",
                      "/programmes", "/academic", "/path/https://" + parsed.netloc + "/ap"]
    target_url = None

    for slug in academic_slugs:
        candidate = root + slug
        html = sel_get(driver, candidate, wait=JS_SETTLE_WAIT)
        if html:
            soup = BeautifulSoup(html, "lxml")
            if soup.find("div", class_=re.compile(r"aca[\-_]?pro", re.I)):
                target_url = candidate
                break

    if not target_url:
        # Try clicking "Academics" from homepage
        sel_get(driver, base_url, wait=JS_SETTLE_WAIT)
        for a_el in sel_find(driver, "a"):
            try:
                if "academic" in a_el.text.lower():
                    href = a_el.get_attribute("href") or ""
                    if href and same_domain(href, base_url):
                        sel_click(driver, a_el, wait=JS_SETTLE_WAIT)
                        html2 = driver.page_source
                        soup2 = BeautifulSoup(html2, "lxml")
                        if soup2.find("div", class_=re.compile(r"aca[\-_]?pro", re.I)):
                            target_url = driver.current_url
                            break
            except Exception:
                continue

    if not target_url:
        return False

    visited.add(target_url)
    page_html = driver.page_source
    soup = BeautifulSoup(page_html, "lxml")

    # Collect all c-links (sub-program links)
    c_links: list[tuple[str, str, str]] = []  # (href, course_name, level)

    for box in soup.find_all("div", class_=re.compile(r"aca[\-_]?pro[\-_]?box", re.I)):
        title_el = box.find(["h1","h2","h3","h4"])
        level_label = title_el.get_text(strip=True) if title_el else "Unknown"
        level = detect_level(level_label)

        for a in box.find_all("a"):
            href = a.get("href","").strip()
            name = a.get_text(strip=True)
            if href and name:
                full_href = urljoin(target_url, href)
                col.add(level_label, name, level, target_url)
                if same_domain(full_href, base_url):
                    c_links.append((full_href, name, level))

    log.debug(f"  Pattern3: {len(c_links)} c-links found")

    # Follow each c-link sub-page
    for href, prog_name, level in c_links[:MAX_PAGES]:
        if href in visited:
            continue
        visited.add(href)
        sub_html = sel_get(driver, href, wait=JS_SETTLE_WAIT)
        if not sub_html:
            sub_html = static_fetch(session, href)
        if sub_html:
            extract_from_html(sub_html, href, col)

    return bool(c_links)

# ══════════════════════════════════════════════════════════════════════════════
# PATTERN 4 — Academics → Courses Offered → individual course → specialisations
#             (NIMS style)
# ══════════════════════════════════════════════════════════════════════════════

def pattern4_courses_offered(driver, session: requests.Session,
                              base_url: str, col: CourseCollector, visited: set[str]):
    """
    1. Load homepage, click 'Academics' in nav
    2. Find 'Courses Offered' link → navigate to it
    3. For each course listed: click it, harvest specialisations
    """
    from selenium.common.exceptions import StaleElementReferenceException

    log.debug(f"  Pattern4 attempting for {base_url}")
    sel_get(driver, base_url, wait=JS_SETTLE_WAIT)

    # ── Step 1: find and click "Academics" nav item ──────────────────────
    academics_url = None
    for a_el in sel_find(driver, "nav a, header a, .navbar a, #menu a, .main-menu a"):
        try:
            txt = a_el.text.strip().lower()
            href = a_el.get_attribute("href") or ""
            if "academic" in txt and href and same_domain(href, base_url):
                academics_url = href
                break
        except Exception:
            continue

    if not academics_url:
        return False

    sel_get(driver, academics_url, wait=JS_SETTLE_WAIT)
    visited.add(academics_url)

    # ── Step 2: find "Courses Offered" link ─────────────────────────────
    courses_offered_url = None
    for a_el in sel_find(driver, "a"):
        try:
            txt = a_el.text.strip().lower()
            href = a_el.get_attribute("href") or ""
            if any(p in txt for p in ["course offered","courses offered",
                                       "course offer","offered course"]) \
               and href and same_domain(href, base_url):
                courses_offered_url = href
                break
        except Exception:
            continue

    # Fallback: look in current page html
    if not courses_offered_url:
        soup_ac = BeautifulSoup(driver.page_source, "lxml")
        for a in soup_ac.find_all("a", href=True):
            txt = a.get_text(strip=True).lower()
            if "course" in txt and "offer" in txt:
                full = urljoin(academics_url, a["href"])
                if same_domain(full, base_url):
                    courses_offered_url = full
                    break

    if not courses_offered_url:
        # Try extracting directly from academics page
        extract_from_html(driver.page_source, academics_url, col)
        return True

    sel_get(driver, courses_offered_url, wait=JS_SETTLE_WAIT)
    visited.add(courses_offered_url)
    co_html = driver.page_source
    extract_from_html(co_html, courses_offered_url, col)

    # ── Step 3: collect all individual course links ──────────────────────
    soup_co = BeautifulSoup(co_html, "lxml")
    strip_noise(soup_co)

    course_links: list[tuple[str, str]] = []  # (url, course_name)
    seen_links: set[str] = set()

    for a in soup_co.find_all("a", href=True):
        href = a["href"].strip()
        name = a.get_text(strip=True)
        if not name or len(name) < 3:
            continue
        full = urljoin(courses_offered_url, href).split("#")[0]
        if not same_domain(full, base_url):
            continue
        if full in seen_links or full in visited:
            continue
        # Filter out obvious nav/footer links
        path = urlparse(full).path.lower()
        if any(bad in path for bad in ["/contact","/about","/home","/gallery",
                                        "/news","/event","/staff","/faculty-member"]):
            continue
        seen_links.add(full)
        course_links.append((full, name))

    log.debug(f"  Pattern4: {len(course_links)} course links found")

    # ── Step 4: visit each course page → grab specialisations ───────────
    for course_url, course_name in course_links[:MAX_COURSE_CLICKS]:
        if course_url in visited:
            continue
        visited.add(course_url)
        time.sleep(0.5)

        c_html = sel_get(driver, course_url, wait=2)
        if not c_html:
            c_html = static_fetch(session, course_url)
        if not c_html:
            continue

        soup_c = BeautifulSoup(c_html, "lxml")
        strip_noise(soup_c)

        # Extract specialisations
        spec_keywords = re.compile(
            r"speciali[sz]ation|speciali[sz]ation|elective|stream|major|track|branch",
            re.I
        )
        spec_list = []

        # Look for lists under a specialisation heading
        for heading in soup_c.find_all(["h2","h3","h4","strong","b","p"]):
            if spec_keywords.search(heading.get_text()):
                # Collect following sibling list items
                sib = heading.find_next_sibling()
                while sib:
                    if sib.name in ["ul","ol"]:
                        for li in sib.find_all("li"):
                            spec_list.append(li.get_text(strip=True))
                    elif sib.name in ["h2","h3","h4"]:
                        break
                    sib = sib.find_next_sibling() if sib else None

        # Also run degree regex on full page
        extract_from_html(c_html, course_url, col)

        # Add course + each specialisation
        for spec in spec_list:
            spec = clean_name(spec)
            if spec:
                col.add(course_name, spec,
                        detect_level(course_name + " " + spec),
                        course_url)

        # If no specialisations found, add the course itself
        if not spec_list:
            col.add(course_name, course_name,
                    detect_level(course_name), course_url)

    return True

# ══════════════════════════════════════════════════════════════════════════════
# SELENIUM DROPDOWN / ACCORDION PASS  (runs on homepage + all key pages)
# ══════════════════════════════════════════════════════════════════════════════

def selenium_full_pass(driver, base_url: str,
                       col: CourseCollector, visited: set[str]):
    """
    Generic Selenium pass:
    • Hover nav items to reveal dropdowns
    • Click Bootstrap / custom dropdown toggles
    • Click accordion + tab buttons
    • Collect all newly revealed internal URLs
    Returns list of newly discovered course-related URLs.
    """
    from selenium.common.exceptions import (
        StaleElementReferenceException, ElementNotInteractableException,
        ElementClickInterceptedException
    )
    from selenium.webdriver.common.action_chains import ActionChains

    new_urls: set[str] = set()
    actions  = ActionChains(driver)

    # ── hover nav items ──────────────────────────────────────────────────
    for sel in ["nav a","header a",".navbar a","#menu a",".main-menu a",
                "[class*='nav'] > li > a","[class*='menu'] > li > a"]:
        for el in sel_find(driver, sel)[:30]:
            try:
                txt = el.text.strip().lower()
                if any(kw in txt for kw in COURSE_NAV_KEYWORDS):
                    actions.move_to_element(el).perform()
                    time.sleep(0.5)
                    for a in sel_find(driver, "a"):
                        href = a.get_attribute("href") or ""
                        if href and same_domain(href, base_url):
                            clean = href.split("#")[0].rstrip("/")
                            if clean not in visited:
                                new_urls.add(clean)
            except (StaleElementReferenceException,
                    ElementNotInteractableException):
                continue

    # ── click dropdown toggles ───────────────────────────────────────────
    for sel in ["[data-toggle='dropdown']","[data-bs-toggle='dropdown']",
                ".dropdown-toggle",".has-dropdown > a",
                ".menu-item-has-children > a","[aria-haspopup='true']"]:
        for el in sel_find(driver, sel)[:MAX_PAGES]:
            try:
                txt = el.text.strip().lower()
                if any(kw in txt for kw in COURSE_NAV_KEYWORDS):
                    sel_click(driver, el, wait=0.7)
                    for a in sel_find(driver, "a"):
                        href = a.get_attribute("href") or ""
                        if href and same_domain(href, base_url):
                            atxt = a.text.strip().lower()
                            if any(kw in (atxt + urlparse(href).path.lower())
                                   for kw in COURSE_NAV_KEYWORDS):
                                new_urls.add(href.split("#")[0].rstrip("/"))
            except (StaleElementReferenceException,
                    ElementNotInteractableException,
                    ElementClickInterceptedException):
                continue

    # ── expand accordions / tabs on current page ─────────────────────────
    for sel in [".accordion-button","[data-toggle='collapse']",
                "[data-bs-toggle='collapse']",".tab-link",
                ".nav-tabs a","[role='tab']","[aria-expanded='false']"]:
        for el in sel_find(driver, sel)[:30]:
            try:
                txt = el.text.strip().lower()
                if any(kw in txt for kw in COURSE_NAV_KEYWORDS + ["+"]):
                    sel_click(driver, el, wait=0.7)
                    extract_from_html(driver.page_source, driver.current_url, col)
            except (StaleElementReferenceException,
                    ElementNotInteractableException,
                    ElementClickInterceptedException):
                continue

    return list(new_urls - visited)

# ══════════════════════════════════════════════════════════════════════════════
# MAIN PER-UNIVERSITY ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════════

def scrape_university(row: dict, output_dir: Path, use_selenium: bool = True) -> dict:
    aishe = row["aishe_code"]
    name  = row["name"]
    raw   = row["website"]

    result: dict = {
        "aishe_code":       aishe,
        "university_name":  name,
        "state":            row["state"],
        "district":         row["district"],
        "website":          raw,
        "year_established": row["year_established"],
        "location_type":    row["location"],
        "scraped_at":       datetime.utcnow().isoformat() + "Z",
        "status":           "pending",
        "pattern_used":     [],
        "courses":          [],
        "total_courses":    0,
        "pages_scraped":    0,
        "errors":           [],
    }

    if not raw or raw in ("-","None",""):
        result["status"] = "no_url"
        result["errors"].append("No website URL available")
        _save(result, output_dir, aishe, name)
        return result

    base_url = normalize_url(raw)
    log.info(f"[{aishe}] {name[:50]}  →  {base_url}")

    col     = CourseCollector()
    visited : set[str] = set()
    session = requests.Session()
    session.max_redirects = 5
    driver  = None

    try:
        # ── Try homepage reachability ────────────────────────────────────
        hp = static_fetch(session, base_url)
        if not hp:
            alt = base_url.replace("//www.","//") if "//www." in base_url \
                  else base_url.replace("//","//www.",1)
            hp = static_fetch(session, alt)
            if hp:
                base_url = alt

        if not hp:
            result["status"] = "unreachable"
            result["errors"].append("Homepage unreachable")
            _save(result, output_dir, aishe, name)
            return result

        # ═════════════════════════════════════════
        # PATTERN 1 — Static nav-following
        # ═════════════════════════════════════════
        pattern1_static(session, base_url, col, visited)
        result["pattern_used"].append("P1-static")

        if use_selenium:
            driver = make_driver()

            # ═════════════════════════════════════════
            # Selenium homepage render + dropdown pass
            # ═════════════════════════════════════════
            sel_html = sel_get(driver, base_url)
            if sel_html:
                extract_from_html(sel_html, base_url, col)

            new_urls = selenium_full_pass(driver, base_url, col, visited)
            result["pattern_used"].append("P1-selenium-dropdown")

            # Scrape newly discovered URLs
            for url in new_urls[:MAX_PAGES]:
                if url in visited:
                    continue
                visited.add(url)
                sub = sel_get(driver, url, wait=2)
                if sub:
                    extract_from_html(sub, url, col)

            # ═════════════════════════════════════════
            # PATTERN 2 — /courses /programmes slugs
            # ═════════════════════════════════════════
            p2 = pattern2_courses_page(driver, session, base_url, col, visited)
            if p2:
                result["pattern_used"].append("P2-course-slugs")

            # ═════════════════════════════════════════
            # PATTERN 3 — aca-pro-box JS SPA (NITW)
            # ═════════════════════════════════════════
            # Check if homepage or any visited page hints at SPA
            has_spa = any("aca-pro" in (static_fetch(session, u) or "") for u in [base_url])
            p3 = pattern3_aca_pro_box(driver, session, base_url, col, visited)
            if p3:
                result["pattern_used"].append("P3-aca-pro-box")

            # ═════════════════════════════════════════
            # PATTERN 4 — Academics → Courses Offered
            #             → each course → specialisations
            # ═════════════════════════════════════════
            p4 = pattern4_courses_offered(driver, session, base_url, col, visited)
            if p4:
                result["pattern_used"].append("P4-courses-offered-drill")

        # ── Finalise ────────────────────────────────────────────────────
        final = col.finalize()
        result["courses"]       = final
        result["total_courses"] = len(final)
        result["pages_scraped"] = len(visited)
        result["status"]        = "success" if final else "no_courses_found"

        log.info(
            f"  ✓ [{aishe}] {name[:40]}  "
            f"→ {len(final)} courses | {len(visited)} pages | "
            f"patterns: {result['pattern_used']}"
        )

    except Exception as e:
        result["status"] = "error"
        result["errors"].append(str(e))
        log.error(f"  ✗ [{aishe}] {name}: {e}")
    finally:
        session.close()
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    _save(result, output_dir, aishe, name)
    return result


def _save(data: dict, output_dir: Path, aishe: str, name: str):
    fname = f"{safe_filename(aishe)}_{safe_filename(name)}.json"
    with open(output_dir / fname, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ══════════════════════════════════════════════════════════════════════════════
# EXCEL LOADER
# ══════════════════════════════════════════════════════════════════════════════

def load_universities(path: str) -> list[dict]:
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    out = []
    for row in rows[1:]:
        aishe, name, state, district, website, year, location = row
        out.append({
            "aishe_code":       str(aishe or "").strip(),
            "name":             str(name or "").strip(),
            "state":            str(state or "").strip(),
            "district":         str(district or "").strip(),
            "website":          str(website or "").strip() if website else None,
            "year_established": str(year or "").strip(),
            "location":         str(location or "").strip(),
        })
    return out


def load_done(output_dir: Path) -> set[str]:
    done = set()
    for f in output_dir.glob("*.json"):
        if f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            done.add(data.get("aishe_code",""))
        except Exception:
            pass
    return done


def save_summary(results: list[dict], output_dir: Path):
    total    = len(results)
    success  = sum(1 for r in results if r["status"] == "success")
    no_url   = sum(1 for r in results if r["status"] == "no_url")
    no_course= sum(1 for r in results if r["status"] == "no_courses_found")
    errors   = sum(1 for r in results if r["status"] in ("error","unreachable"))
    total_c  = sum(r.get("total_courses",0) for r in results)

    level_counts: dict[str,int] = {}
    pattern_counts: dict[str,int] = {}
    for r in results:
        for c in r.get("courses",[]):
            lv = c.get("level_of_education","Unknown")
            level_counts[lv] = level_counts.get(lv,0) + 1
        for p in r.get("pattern_used",[]):
            pattern_counts[p] = pattern_counts.get(p,0) + 1

    summary = {
        "generated_at":           datetime.utcnow().isoformat() + "Z",
        "total_universities":     total,
        "scraped_successfully":   success,
        "no_url":                 no_url,
        "no_courses_found":       no_course,
        "errors_unreachable":     errors,
        "total_courses_extracted":total_c,
        "courses_by_level":       level_counts,
        "patterns_triggered":     pattern_counts,
        "universities": [
            {
                "aishe_code":    r["aishe_code"],
                "name":          r["university_name"],
                "status":        r["status"],
                "courses_found": r.get("total_courses",0),
                "pages_scraped": r.get("pages_scraped",0),
                "patterns":      r.get("pattern_used",[]),
            }
            for r in results
        ],
    }

    (output_dir / "_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    log.info("=" * 65)
    log.info("FINAL SUMMARY")
    log.info(f"  Universities        : {total}")
    log.info(f"  Success             : {success}")
    log.info(f"  No URL              : {no_url}")
    log.info(f"  No courses found    : {no_course}")
    log.info(f"  Errors/Unreachable  : {errors}")
    log.info(f"  Total courses       : {total_c}")
    log.info(f"  Courses by level    :")
    for lv, cnt in sorted(level_counts.items(), key=lambda x:-x[1]):
        log.info(f"    {lv:<35}: {cnt}")
    log.info(f"  Patterns triggered  : {pattern_counts}")
    log.info("=" * 65)

# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="University Course Scraper v3")
    parser.add_argument("--excel",       default=EXCEL_FILE)
    parser.add_argument("--output",      default=OUTPUT_DIR)
    parser.add_argument("--limit",       type=int, default=0,
                        help="Max universities to scrape (0=all)")
    parser.add_argument("--start",       type=int, default=0,
                        help="Start index (0-based)")
    parser.add_argument("--workers",     type=int, default=MAX_WORKERS,
                        help="Parallel Chrome workers")
    parser.add_argument("--resume",      action="store_true",
                        help="Skip already-scraped universities")
    parser.add_argument("--no-selenium", action="store_true",
                        help="Static only — faster but misses JS/dropdown sites")
    parser.add_argument("--fast", action="store_true",
                        help="Fast mode = --no-selenium + higher workers")
    args = parser.parse_args()
    
    # Auto-enable static mode if --fast requested
    if args.fast:
        args.no_selenium = True
        args.workers = min(10, args.workers * 2)  # Double workers for fast mode

    output_dir = Path(args.output)
    output_dir.mkdir(exist_ok=True)

    if not Path(args.excel).exists():
        log.error(f"Excel not found: {args.excel}")
        sys.exit(1)

    universities = load_universities(args.excel)
    log.info(f"Loaded {len(universities)} universities from {args.excel}")

    universities = universities[args.start:]
    if args.limit:
        universities = universities[:args.limit]

    if args.resume:
        done  = load_done(output_dir)
        before = len(universities)
        universities = [u for u in universities if u["aishe_code"] not in done]
        log.info(f"Resume: skipping {before-len(universities)}, {len(universities)} remaining")

    use_selenium = not args.no_selenium
    if use_selenium:
        try:
            import selenium                                           # noqa
            from webdriver_manager.chrome import ChromeDriverManager # noqa
            log.info("✓ Selenium enabled — all 4 patterns active")
        except ImportError:
            log.warning("selenium/webdriver-manager not installed → static-only mode")
            log.warning("Run:  pip install selenium webdriver-manager")
            use_selenium = False

    log.info(
        f"Scraping {len(universities)} universities | "
        f"workers={args.workers} | selenium={use_selenium}"
    )
    log.info(
        "Patterns: P1=static-nav | P2=course-slugs | "
        "P3=aca-pro-box | P4=courses-offered-drill"
    )

    results   = []
    done_cnt  = 0
    t0        = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {
            ex.submit(scrape_university, u, output_dir, use_selenium): u
            for u in universities
        }
        for fut in as_completed(futures):
            u = futures[fut]
            try:
                res = fut.result()
                results.append(res)
            except Exception as e:
                log.error(f"Fatal: {u['name']}: {e}")
                results.append({
                    "aishe_code":      u["aishe_code"],
                    "university_name": u["name"],
                    "status":          "error",
                    "courses":         [],
                    "total_courses":   0,
                    "pages_scraped":   0,
                    "pattern_used":    [],
                    "errors":          [str(e)],
                })

            done_cnt += 1
            elapsed = time.time() - t0
            rate    = done_cnt / elapsed if elapsed > 0 else 0
            eta     = (len(universities) - done_cnt) / rate / 60 if rate > 0 else 0
            log.info(
                f"Progress {done_cnt}/{len(universities)} "
                f"({100*done_cnt/len(universities):.1f}%) | "
                f"{rate:.2f}/s | ETA {eta:.1f} min"
            )

    save_summary(results, output_dir)
    log.info(f"All done! → {output_dir.resolve()}")


if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()