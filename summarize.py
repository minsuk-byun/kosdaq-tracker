"""Step 2 — write an English summary for each collected filing, then check it.

Every number in the English summary must match a number in the Korean source
(after converting units such as 억원 / 조원 / bn / million). If any number has no
match, the filing goes to data/held/ with the reason and is NOT published.

Usage:
    python summarize.py          # needs ANTHROPIC_API_KEY
    DEMO=1 python summarize.py   # uses pre-written sample summaries
"""
import json
import re
import sys
import time

import requests

import config as C

PROMPT = """You are writing for an English-language website that summarizes Korean stock
exchange filings for foreign investors. Below is the original Korean filing.

Company (Korean): {corp_name}
Company (English, from DART): {corp_name_eng}
Report: {report_nm}
Event type: {event_label}

Write a factual summary. Rules:
- Use only facts stated in the filing. Do not guess, predict, or give opinions on the stock.
- Never recommend buying or selling.
- Every number you write must appear in the filing (you may convert units: 50억원 = KRW 5bn,
  5,000,000,000원 = KRW 5bn). Write money as "KRW 5bn", "KRW 320m", "KRW 1.2tn".
- Do not compute new numbers (no ratios, sums or differences that the filing does not state).
- Dates as "Nov 3, 2026".
- "why_it_matters" explains in general terms what this TYPE of filing usually means for
  shareholders in Korea. It must not judge this particular company.

Return only JSON with these keys:
{{"headline": "<max 90 chars: company + what happened + the key number>",
 "what_happened": "<2-3 sentences>",
 "key_numbers": [{{"label": "<short label>", "value": "<value as written for readers>"}}],
 "why_it_matters": "<1-2 sentences>",
 "company_short": "<company name in English as readers would know it>"}}
key_numbers: 2 to 6 items.

<filing>
{text}
</filing>"""


def call_model(rec):
    ev = C.EVENTS_BY_KEY[rec["event"]]
    body = {
        "model": C.ANTHROPIC_MODEL,
        "max_tokens": 900,
        "messages": [{"role": "user", "content": PROMPT.format(
            corp_name=rec["corp_name"], corp_name_eng=rec.get("corp_name_eng") or "-",
            report_nm=rec["report_nm"], event_label=ev["label"], text=rec["text"])}],
    }
    headers = {"x-api-key": C.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    for attempt in range(4):
        r = requests.post("https://api.anthropic.com/v1/messages", json=body,
                          headers=headers, timeout=90)
        if r.status_code in (429, 500, 502, 503, 529):
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json()["content"] if b["type"] == "text")
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ValueError("model did not return JSON")
        return json.loads(m.group(0))
    raise RuntimeError("model API kept failing")


# --- number check ------------------------------------------------------------
EN_MULT = {"tn": 1e12, "trillion": 1e12, "bn": 1e9, "billion": 1e9, "m": 1e6,
           "mn": 1e6, "million": 1e6, "k": 1e3, "thousand": 1e3}
EN_NUM = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(tn|trillion|bn|billion|mn|million|m|k|thousand)?(?![\w])",
    re.I)
KO_NUM = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(조|억|만|천)?")
KO_MULT = {"조": 1e12, "억": 1e8, "만": 1e4, "천": 1e3}


def source_numbers(text):
    vals = {float(t) for t in re.findall(r"\d+", text)}  # plain digit runs (dates etc.)
    for m in KO_NUM.finditer(text):
        base = float(m.group(1).replace(",", "") + (m.group(2) or ""))
        vals.add(base)
        if m.group(3):
            vals.add(base * KO_MULT[m.group(3)])
    # "1조 2,000억" style compound amounts
    for m in re.finditer(r"(\d+)\s*조\s*(\d{1,3}(?:,\d{3})*|\d+)\s*억", text):
        vals.add(float(m.group(1)) * 1e12 + float(m.group(2).replace(",", "")) * 1e8)
    return vals


def summary_numbers(summary):
    parts = [summary.get("headline", ""), summary.get("what_happened", ""),
             summary.get("why_it_matters", "")]
    parts += [kn.get("value", "") for kn in summary.get("key_numbers", [])]
    found = []
    for part in parts:
        for m in EN_NUM.finditer(part):
            base = float(m.group(1).replace(",", "") + (m.group(2) or ""))
            unit = (m.group(3) or "").lower()
            found.append((m.group(0).strip(), base * EN_MULT.get(unit, 1)))
    return found


def matches(value, pool):
    for s in pool:
        if value == s:
            return True
        if s and abs(value - s) / abs(s) <= 0.006:  # allow rounding like 4.98bn -> 5bn
            return True
    return False


def check_numbers(summary, text):
    pool = source_numbers(text)
    # Month names in English dates are words, so "Nov 3, 2026" -> 3 and 2026, both in source.
    bad = [raw for raw, val in summary_numbers(summary) if not matches(val, pool)]
    return list(dict.fromkeys(bad))


def check_shape(summary):
    problems = []
    for key in ("headline", "what_happened", "why_it_matters"):
        if not str(summary.get(key, "")).strip():
            problems.append(f"missing {key}")
    if not 1 <= len(summary.get("key_numbers", [])) <= 8:
        problems.append("key_numbers count")
    banned = re.compile(r"\b(recommend\w*|strong buy|should (buy|sell)|undervalued|overvalued|"
                        r"target price|price target|must-buy|bargain)\b", re.I)
    for key in ("headline", "what_happened", "why_it_matters"):
        if banned.search(str(summary.get(key, ""))):
            problems.append(f"advice-like wording in {key}")
    return problems


def main():
    raws = sorted(C.RAW_DIR.glob("*.json"))
    if not raws:
        print("nothing to summarize")
        return
    demo_summaries = {}
    if C.DEMO:
        p = C.DEMO_DIR / "summaries.json"
        demo_summaries = json.loads(p.read_text(encoding="utf-8"))
    elif not C.ANTHROPIC_API_KEY:
        sys.exit("ANTHROPIC_API_KEY is not set (or run with DEMO=1)")

    published = held = 0
    for path in raws:
        rec = json.loads(path.read_text(encoding="utf-8"))
        try:
            summary = (demo_summaries[rec["rcept_no"]] if C.DEMO else call_model(rec))
        except Exception as exc:  # leave in raw/ to retry next run
            print(f"  ! {rec['rcept_no']} {exc}", file=sys.stderr)
            continue
        bad = check_numbers(summary, rec["text"])
        problems = check_shape(summary) + [f"number not in source: {b}" for b in bad]
        rec["summary"] = summary
        if problems:
            rec["held_reasons"] = problems
            (C.HELD_DIR / path.name).write_text(
                json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            held += 1
            print(f"  HOLD {rec['corp_name']}: {'; '.join(problems)}")
        else:
            rec.pop("text", None)  # source text is not republished
            (C.FILINGS_DIR / path.name).write_text(
                json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            published += 1
            print(f"  ok   {summary['headline']}")
        path.unlink()
    print(f"published {published}, held {held}")


if __name__ == "__main__":
    main()
