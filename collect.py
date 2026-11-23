"""Step 1 — collect new filings from OpenDART.

Usage:
    python collect.py                 # today's filings (Korea time)
    python collect.py --date 20261103 # a specific day
    python collect.py --days 3        # today and the 2 days before
    DEMO=1 python collect.py          # copy sample filings instead (no API key)

Writes one JSON file per filing to data/raw/<rcept_no>.json.
"""
import argparse
import io
import json
import re
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone
from html import unescape

import requests

import config as C

API = "https://opendart.fss.or.kr/api"
KST = timezone(timedelta(hours=9))
session = requests.Session()
session.headers["User-Agent"] = "korea-smallcap-filings/1.0"


class DartError(RuntimeError):
    pass


def dart_get(path, **params):
    params["crtfc_key"] = C.DART_API_KEY
    for attempt in range(3):
        try:
            r = session.get(f"{API}/{path}", params=params, timeout=30)
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            if attempt == 2:
                raise DartError(f"{path}: {exc}") from exc
            time.sleep(2 * (attempt + 1))


def dart_json(path, **params):
    data = dart_get(path, **params).json()
    status = data.get("status")
    if status == "013":  # no data for this query
        return None
    if status != "000":
        # 010/011 = bad key, 020 = daily call limit reached
        raise DartError(f"{path}: status {status} {data.get('message')}")
    return data


def list_filings(day: str):
    """All filings for one day in the configured markets."""
    out = []
    for market in C.MARKETS:
        page = 1
        while True:
            data = dart_json("list.json", bgn_de=day, end_de=day, corp_cls=market,
                             page_no=page, page_count=100)
            if not data:
                break
            out.extend(data.get("list", []))
            if page >= int(data.get("total_page", 1)):
                break
            page += 1
            time.sleep(0.2)
    return out


def load_company_cache():
    if C.COMPANY_CACHE.exists():
        return json.loads(C.COMPANY_CACHE.read_text(encoding="utf-8"))
    return {}


def company_info(corp_code, cache):
    if corp_code in cache:
        return cache[corp_code]
    data = dart_json("company.json", corp_code=corp_code) or {}
    info = {
        "corp_name": data.get("corp_name", ""),
        "corp_name_eng": (data.get("corp_name_eng") or "").strip(),
        "stock_code": data.get("stock_code", ""),
        "corp_cls": data.get("corp_cls", ""),
        "ceo_nm": data.get("ceo_nm", ""),
        "est_dt": data.get("est_dt", ""),
        "hm_url": data.get("hm_url", ""),
        "induty_code": data.get("induty_code", ""),
    }
    cache[corp_code] = info
    return info


TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t ]+")


def document_text(rcept_no):
    """Plain text of the original filing (document.xml returns a zip)."""
    r = dart_get("document.xml", rcept_no=rcept_no)
    if not r.content.startswith(b"PK"):
        raise DartError(f"document {rcept_no}: not a zip ({r.text[:120]})")
    parts = []
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for name in sorted(z.namelist()):
            raw = z.read(name)
            for enc in ("utf-8", "euc-kr", "cp949"):
                try:
                    text = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                text = raw.decode("utf-8", "ignore")
            text = re.sub(r"(?i)</(p|tr|table|title|section-\d|td|th)>|<br\s*/?>", "\n", text)
            text = unescape(TAG_RE.sub(" ", text))
            parts.append(text)
    text = "\n".join(parts)
    lines = [WS_RE.sub(" ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def load_excluded():
    if not C.EXCLUDE_FILE.exists():
        return set()
    codes = set()
    for line in C.EXCLUDE_FILE.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line:
            codes.add(line)
    return codes


def already_have(rcept_no):
    return any((d / f"{rcept_no}.json").exists()
               for d in (C.RAW_DIR, C.FILINGS_DIR, C.HELD_DIR))


def collect_day(day, cache, excluded):
    saved = 0
    for item in list_filings(day):
        event = C.classify(item["report_nm"])
        if not event:
            continue
        if item.get("stock_code") in excluded or item.get("corp_code") in excluded:
            continue
        rcept_no = item["rcept_no"]
        if already_have(rcept_no):
            continue
        info = company_info(item["corp_code"], cache)
        try:
            text = document_text(rcept_no)
        except DartError as exc:
            print(f"  skip {rcept_no}: {exc}", file=sys.stderr)
            continue
        record = {
            "rcept_no": rcept_no,
            "rcept_dt": item["rcept_dt"],
            "corp_code": item["corp_code"],
            "corp_name": item["corp_name"],
            "corp_name_eng": info.get("corp_name_eng", ""),
            "stock_code": item.get("stock_code") or info.get("stock_code", ""),
            "corp_cls": item.get("corp_cls", ""),
            "report_nm": item["report_nm"].strip(),
            "event": event,
            "amended": C.is_amended(item["report_nm"]),
            "dart_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
            "text": text[: C.MAX_SOURCE_CHARS],
        }
        (C.RAW_DIR / f"{rcept_no}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        saved += 1
        print(f"  + {record['corp_name']} | {record['report_nm']}")
        time.sleep(0.3)
    return saved


def collect_demo():
    n = 0
    records = json.loads((C.DEMO_DIR / "raw_filings.json").read_text(encoding="utf-8"))
    for rec in records:
        if not already_have(rec["rcept_no"]):
            rec.setdefault("dart_url", "")
            rec.setdefault("amended", C.is_amended(rec["report_nm"]))
            (C.RAW_DIR / f"{rec['rcept_no']}.json").write_text(
                json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            n += 1
    demo_companies = C.DEMO_DIR / "companies.json"
    if demo_companies.exists():
        cache = load_company_cache()
        cache.update(json.loads(demo_companies.read_text(encoding="utf-8")))
        C.COMPANY_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    print(f"demo: copied {n} sample filings")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYYMMDD (default: today in Korea)")
    ap.add_argument("--days", type=int, default=1, help="how many days back to scan")
    args = ap.parse_args()

    for d in (C.RAW_DIR, C.FILINGS_DIR, C.HELD_DIR):
        d.mkdir(parents=True, exist_ok=True)

    if C.DEMO:
        collect_demo()
        return
    if not C.DART_API_KEY:
        sys.exit("DART_API_KEY is not set (or run with DEMO=1)")

    end = (datetime.strptime(args.date, "%Y%m%d").replace(tzinfo=KST)
           if args.date else datetime.now(KST))
    cache, excluded = load_company_cache(), load_excluded()
    total = 0
    try:
        for i in range(args.days):
            day = (end - timedelta(days=i)).strftime("%Y%m%d")
            print(f"collecting {day}")
            total += collect_day(day, cache, excluded)
    finally:
        C.COMPANY_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    print(f"collected {total} new filings")


if __name__ == "__main__":
    main()
