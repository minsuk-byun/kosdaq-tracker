"""Step 3 — turn published filings + guides into a static website in site/.

Usage:
    python build.py          # live data
    DEMO=1 python build.py   # adds a "demo data" banner
"""
import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

import config as C

env = Environment(loader=FileSystemLoader(C.TEMPLATES_DIR),
                  autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)


def slugify(text):
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return text[:60] or "filing"


def fmt_date(yyyymmdd):
    return datetime.strptime(yyyymmdd, "%Y%m%d").strftime("%b %-d, %Y")


def iso_date(yyyymmdd):
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


env.filters["nicedate"] = fmt_date
env.filters["isodate"] = iso_date


def load_filings():
    companies = {}
    if C.COMPANY_CACHE.exists():
        companies = json.loads(C.COMPANY_CACHE.read_text(encoding="utf-8"))
    filings = []
    for p in C.FILINGS_DIR.glob("*.json"):
        f = json.loads(p.read_text(encoding="utf-8"))
        s = f["summary"]
        ev = C.EVENTS_BY_KEY[f["event"]]
        name_en = (s.get("company_short") or f.get("corp_name_eng") or f["corp_name"]).strip()
        f["company_en"] = name_en
        f["event_info"] = ev
        f["market"] = C.MARKET_LABEL.get(f.get("corp_cls", ""), "")
        f["slug"] = f"{slugify(name_en)}-{ev['short'].lower().replace(' ', '-')}-{f['rcept_no'][-6:]}"
        f["url"] = f"/filings/{iso_date(f['rcept_dt'])}/{slugify(f['slug'])}/"
        f["company_url"] = f"/companies/{f['stock_code']}/" if f.get("stock_code") else ""
        f["company_info"] = companies.get(f["corp_code"], {})
        filings.append(f)
    filings.sort(key=lambda f: f["rcept_no"], reverse=True)
    return filings


def load_guides():
    guides = []
    for p in sorted(C.GUIDES_DIR.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        meta, body = {}, text
        if text.startswith("---"):
            _, head, body = text.split("---", 2)
            for line in head.strip().splitlines():
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
        if meta.get("draft", "").lower() == "true":
            continue
        slug = meta.get("slug") or p.stem
        guides.append({
            "slug": slug, "url": f"/guides/{slug}/",
            "title": meta.get("title", slug), "description": meta.get("description", ""),
            "updated": meta.get("updated", ""), "events": meta.get("events", ""),
            "html": markdown.markdown(body, extensions=["tables", "toc"]),
        })
    return guides


def load_pages():
    pages = []
    for p in sorted((C.TEMPLATES_DIR / "pages").glob("*.md")):
        text = p.read_text(encoding="utf-8")
        title, _, body = text.partition("\n")
        for k, v in {"{{SITE_NAME}}": C.SITE_NAME, "{{CONTACT_EMAIL}}": C.CONTACT_EMAIL,
                     "{{SITE_URL}}": C.SITE_URL,
                     "{{UPDATED}}": datetime.now(timezone.utc).strftime("%B %-d, %Y")}.items():
            body = body.replace(k, v)
        pages.append({"slug": p.stem, "url": f"/{p.stem}/", "title": title.lstrip("# ").strip(),
                      "html": markdown.markdown(body, extensions=["tables"])})
    return pages


LOCAL_LINK = re.compile(r'((?:href|src)=")/(?!/)')


def write(url, html):
    if C.BASE_PATH and (url.endswith("/") or url.endswith(".html")):
        html = LOCAL_LINK.sub(rf"\1{C.BASE_PATH}/", html)
    out = C.SITE_DIR / url.strip("/") / "index.html" if url.endswith("/") else C.SITE_DIR / url.lstrip("/")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")


def render(template, **ctx):
    return env.get_template(template).render(**ctx)


def main():
    if C.SITE_DIR.exists():
        shutil.rmtree(C.SITE_DIR)
    shutil.copytree(C.STATIC_DIR, C.SITE_DIR / "static")

    filings, guides, pages = load_filings(), load_guides(), load_pages()
    by_day, by_event, by_company = defaultdict(list), defaultdict(list), defaultdict(list)
    for f in filings:
        by_day[f["rcept_dt"]].append(f)
        by_event[f["event"]].append(f)
        if f.get("stock_code"):
            by_company[f["stock_code"]].append(f)
    days = sorted(by_day, reverse=True)
    guide_for_event = {}
    for g in guides:
        for key in filter(None, (k.strip() for k in g["events"].split(","))):
            guide_for_event.setdefault(key, g)

    common = dict(
        site_name=C.SITE_NAME, tagline=C.SITE_TAGLINE, site_url=C.SITE_URL, demo=C.DEMO,
        events=C.EVENT_TYPES, adsense=C.ADSENSE_PUB_ID, slot_article=C.ADSENSE_SLOT_INARTICLE,
        slot_list=C.ADSENSE_SLOT_LIST, footer_pages=pages, year=datetime.now().year,
        latest_day=days[0] if days else "",
    )
    urls = ["/"]

    write("/", render("index.html", **common, page_title="", canonical="/",
                      description=C.SITE_TAGLINE, latest=filings[:12], days=days[:10],
                      by_day=by_day, event_counts=Counter(f["event"] for f in filings),
                      guides=guides[:6], total=len(filings), companies=len(by_company)))

    for f in filings:
        related = [x for x in by_company.get(f.get("stock_code"), []) if x is not f][:5]
        write(f["url"], render(
            "filing.html", **common, f=f, s=f["summary"], related=related,
            guide=guide_for_event.get(f["event"]), canonical=f["url"],
            page_title=f["summary"]["headline"],
            description=f["summary"]["what_happened"][:155]))
        urls.append(f["url"])

    for day in days:
        url = f"/daily/{iso_date(day)}/"
        write(url, render("list.html", **common, items=by_day[day], canonical=url,
                          heading=f"Filings on {fmt_date(day)}",
                          intro=f"{len(by_day[day])} covered disclosures filed on {fmt_date(day)}.",
                          page_title=f"Korean small-cap filings, {fmt_date(day)}",
                          description=f"English summaries of {len(by_day[day])} KOSDAQ and small-cap filings on {fmt_date(day)}."))
        urls.append(url)

    for ev in C.EVENT_TYPES:
        url = f"/events/{ev['slug']}/"
        items = by_event.get(ev["key"], [])
        write(url, render("list.html", **common, items=items, canonical=url, heading=ev["label"],
                          intro=ev["blurb"], guide=guide_for_event.get(ev["key"]),
                          page_title=f"{ev['label']} — Korean small caps",
                          description=f"{ev['blurb']} Latest KOSDAQ and small-cap filings in English."))
        urls.append(url)

    for code, items in by_company.items():
        f0 = items[0]
        info = f0["company_info"]
        url = f0["company_url"]
        write(url, render("company.html", **common, items=items, f0=f0, info=info, canonical=url,
                          counts=Counter(x["event"] for x in items),
                          page_title=f"{f0['company_en']} ({code}) filings in English",
                          description=f"English summaries of {f0['company_en']} ({f0['corp_name']}, {code}) disclosures: buybacks, dividends, capital raises and more."))
        urls.append(url)

    write("/guides/", render("guides.html", **common, guides=guides, canonical="/guides/",
                             page_title="Guides to Korean stock filings",
                             description="Plain-English guides to Korean disclosure terms and the KOSDAQ market."))
    urls.append("/guides/")
    for g in guides:
        write(g["url"], render("guide.html", **common, g=g, canonical=g["url"],
                               page_title=g["title"], description=g["description"]))
        urls.append(g["url"])

    for p in pages:
        write(p["url"], render("page.html", **common, p=p, canonical=p["url"],
                               page_title=p["title"], description=f"{p['title']} — {C.SITE_NAME}"))
        urls.append(p["url"])

    write("/404.html", render("page.html", **common, canonical="/404.html", page_title="Not found",
                              description="Page not found",
                              p={"title": "Page not found",
                                 "html": '<p>This page does not exist. <a href="/">Go to today\'s filings</a>.</p>'}))

    # sitemap, robots, feed, ads.txt
    sm = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sm += [f"<url><loc>{escape(C.SITE_URL + u)}</loc></url>" for u in urls]
    sm.append("</urlset>")
    write("/sitemap.xml", "\n".join(sm))
    write("/robots.txt", f"User-agent: *\nAllow: /\nSitemap: {C.SITE_URL}/sitemap.xml\n")
    now = format_datetime(datetime.now(timezone.utc))
    items = []
    for f in filings[:50]:
        d = datetime.strptime(f["rcept_dt"], "%Y%m%d").replace(tzinfo=timezone.utc)
        items.append(f"<item><title>{escape(f['summary']['headline'])}</title>"
                     f"<link>{C.SITE_URL}{f['url']}</link><guid>{C.SITE_URL}{f['url']}</guid>"
                     f"<pubDate>{format_datetime(d)}</pubDate>"
                     f"<description>{escape(f['summary']['what_happened'])}</description></item>")
    write("/feed.xml", '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
          f"<title>{escape(C.SITE_NAME)}</title><link>{C.SITE_URL}/</link>"
          f"<description>{escape(C.SITE_TAGLINE)}</description><lastBuildDate>{now}</lastBuildDate>"
          + "".join(items) + "</channel></rss>")
    if C.ADSENSE_PUB_ID:
        pub = C.ADSENSE_PUB_ID.replace("ca-", "")
        write("/ads.txt", f"google.com, {pub}, DIRECT, f08c47fec0942fa0\n")

    print(f"built {len(urls)} pages into {C.SITE_DIR}")


if __name__ == "__main__":
    main()
