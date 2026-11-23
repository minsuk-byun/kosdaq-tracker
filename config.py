"""Site settings and the disclosure types the tracker covers.

Most values can be overridden with environment variables so the same code
runs locally (demo mode) and on GitHub Actions (live mode).
"""
import os
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RAW_DIR = DATA / "raw"          # collected filings (Korean source text)
FILINGS_DIR = DATA / "filings"  # summarized, verified, ready to publish
HELD_DIR = DATA / "held"        # failed the number check: not published
DEMO_DIR = DATA / "demo"        # sample data for demo mode
COMPANY_CACHE = DATA / "companies.json"
EXCLUDE_FILE = DATA / "exclude.txt"
GUIDES_DIR = ROOT / "guides"
TEMPLATES_DIR = ROOT / "templates"
STATIC_DIR = ROOT / "static"
SITE_DIR = ROOT / "site"

# --- environment -----------------------------------------------------------
DEMO = os.environ.get("DEMO", "") == "1"
DART_API_KEY = os.environ.get("DART_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5")

# `or` (not a get() default): GitHub Actions passes unset variables as empty strings.
SITE_NAME = os.environ.get("SITE_NAME") or "Korea Small-Cap Filings"
SITE_TAGLINE = (os.environ.get("SITE_TAGLINE")
                or "Daily English summaries of KOSDAQ and small-cap disclosures from Korea's DART")
SITE_URL = (os.environ.get("SITE_URL") or "https://example.com").rstrip("/")
# A site served from a sub-folder (e.g. https://user.github.io/kosdaq-tracker) needs every
# internal link prefixed with that folder. With a custom domain this is empty.
BASE_PATH = urlparse(SITE_URL).path.rstrip("/")
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL") or "contact@example.com"
ADSENSE_PUB_ID = (os.environ.get("ADSENSE_PUB_ID") or "").strip()  # ca-pub-XXXXXXXXXXXXXXXX
# Optional manual ad units (leave empty to rely on Auto ads only)
ADSENSE_SLOT_INARTICLE = os.environ.get("ADSENSE_SLOT_INARTICLE", "").strip()
ADSENSE_SLOT_LIST = os.environ.get("ADSENSE_SLOT_LIST", "").strip()

# Markets to collect: K = KOSDAQ, Y = KOSPI (large KOSPI names go in exclude.txt)
MARKETS = [m for m in os.environ.get("MARKETS", "K,Y").split(",") if m]
MAX_SOURCE_CHARS = 14000  # source text sent to the model per filing

# Large KOSPI groups whose big affiliates already publish official English disclosures.
# A KOSPI company whose Korean name starts with one of these is skipped. This is a rough
# rule of thumb: edit the list, or use data/exclude.txt for single companies.
LARGE_KOSPI_PREFIXES = [
    "삼성", "SK", "에스케이", "LG", "엘지", "현대", "HD", "기아", "한화", "롯데", "포스코",
    "POSCO", "GS", "CJ", "KT", "신세계", "두산", "LS", "셀트리온", "카카오", "NAVER", "네이버",
    "신한", "KB", "하나", "우리", "메리츠", "대한항공", "고려아연", "HMM", "S-Oil", "에쓰오일",
    "한국전력", "한국가스공사", "한국항공우주", "대우건설", "KT&G", "아모레", "효성", "코웨이",
]


def is_large_kospi(corp_cls: str, corp_name: str) -> bool:
    return corp_cls == "Y" and any(corp_name.startswith(p) for p in LARGE_KOSPI_PREFIXES)

# --- disclosure types --------------------------------------------------------
# `match` strings are compared against DART's report name with spaces and
# middle dots removed, so "현금ㆍ현물배당결정" and "현금 현물배당 결정" both match.
EVENT_TYPES = [
    {
        "key": "buyback",
        "slug": "share-buybacks",
        "label": "Share buybacks & cancellations",
        "short": "Buyback",
        "match": ["자기주식취득결정", "자기주식소각결정", "주식소각결정",
                  "자기주식취득신탁계약체결결정"],
        "blurb": "Companies buying back or cancelling their own shares.",
    },
    {
        "key": "dividend",
        "slug": "dividends",
        "label": "Dividend decisions",
        "short": "Dividend",
        "match": ["현금현물배당결정", "현금배당결정", "현물배당결정"],
        "blurb": "Cash and in-kind dividend announcements, with record dates.",
    },
    {
        "key": "capital",
        "slug": "rights-offerings-and-convertibles",
        "label": "Rights offerings & convertible bonds",
        "short": "Capital raise",
        "match": ["유상증자결정", "전환사채권발행결정", "신주인수권부사채권발행결정",
                  "교환사채권발행결정"],
        "blurb": "New shares, convertible bonds and warrants that can dilute holders.",
    },
    {
        "key": "control",
        "slug": "change-of-control",
        "label": "Change of largest shareholder",
        "short": "Control change",
        "match": ["최대주주변경"],
        "blurb": "A new largest shareholder, often the start of a strategic shift.",
    },
    {
        "key": "contract",
        "slug": "major-contracts",
        "label": "Major supply contracts",
        "short": "Contract",
        "match": ["단일판매공급계약체결"],
        "blurb": "Single sales or supply contracts large enough to require disclosure.",
    },
    {
        "key": "mna",
        "slug": "mergers-and-splits",
        "label": "Mergers, splits & business transfers",
        "short": "M&A",
        "match": ["회사합병결정", "회사분할결정", "회사분할합병결정", "영업양수결정",
                  "영업양도결정", "주식교환이전결정", "타법인주식및출자증권취득결정"],
        "blurb": "Mergers, spin-offs, and purchases or sales of businesses.",
    },
]
EVENTS_BY_KEY = {e["key"]: e for e in EVENT_TYPES}

MARKET_LABEL = {"K": "KOSDAQ", "Y": "KOSPI", "N": "KONEX", "E": "Other"}


def normalize_report_name(name: str) -> str:
    for ch in " ㆍ·・ ":
        name = name.replace(ch, "")
    return name


def classify(report_nm: str):
    """Return the event key for a DART report name, or None if not covered."""
    norm = normalize_report_name(report_nm)
    for ev in EVENT_TYPES:
        if any(m in norm for m in ev["match"]):
            return ev["key"]
    return None


def is_amended(report_nm: str) -> bool:
    return "정정" in report_nm.split("]")[0] if report_nm.startswith("[") else False
