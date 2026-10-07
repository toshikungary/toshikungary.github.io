#!/usr/bin/env python3
"""Build an RSS feed from https://www.headline4hk.com/latest-news

Output: rss/feed.xml  (relative to where the script is run)
Requires: pip install requests beautifulsoup4

Personal use only. The page structure may change; if the feed comes out
empty, inspect the HTML and adjust the selectors below.
"""
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from urllib.parse import urljoin
from xml.sax.saxutils import escape

import requests
from bs4 import BeautifulSoup

URL = "https://www.headline4hk.com/latest-news"
OUT_PATH = os.path.join("rss", "feed.xml")
HKT = timezone(timedelta(hours=8))

# Optional: keep only headlines containing any of these keywords.
# Leave empty to keep everything, e.g. KEYWORDS = ["立法會", "港股"]
KEYWORDS = []


def fetch_html():
    r = requests.get(
        URL,
        headers={"User-Agent": "Mozilla/5.0 (personal RSS builder)"},
        timeout=20,
    )
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def parse_time(text, now):
    """Parse 'MM-DD HH:MM' (HKT). Handle year rollover in early January."""
    m = re.search(r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", text or "")
    if not m:
        return now
    mo, d, hh, mm = map(int, m.groups())
    try:
        dt = datetime(now.year, mo, d, hh, mm, tzinfo=HKT)
    except ValueError:
        return now
    if dt > now + timedelta(days=1):
        dt = dt.replace(year=now.year - 1)
    return dt


def parse_items(html):
    soup = BeautifulSoup(html, "html.parser")
    now = datetime.now(HKT)
    items, seen = [], set()

    for tr in soup.select("tr"):
        a = next(
            (
                x
                for x in tr.find_all("a", href=True)
                if "/article/" in x["href"] and x.get_text(strip=True)
            ),
            None,
        )
        if not a:
            continue

        link = urljoin(URL, a["href"])
        if link in seen:
            continue
        seen.add(link)

        title = a.get_text(strip=True)
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        source = cells[3] if len(cells) > 3 else ""
        when = parse_time(cells[0] if cells else "", now)

        if KEYWORDS and not any(k in title for k in KEYWORDS):
            continue

        items.append({"title": title, "link": link, "source": source, "date": when})

    items.sort(key=lambda i: i["date"], reverse=True)
    return items


def build_rss(items):
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0"><channel>',
        "<title>Headline4HK 即時新聞（個人用）</title>",
        "<link>https://www.headline4hk.com</link>",
        "<description>Unofficial personal feed built from headline4hk.com</description>",
        "<language>zh-HK</language>",
        f"<lastBuildDate>{format_datetime(datetime.now(HKT))}</lastBuildDate>",
    ]
    for i in items:
        label = f"[{i['source']}] " if i["source"] else ""
        parts.append(
            "<item>"
            f"<title>{escape(label + i['title'])}</title>"
            f"<link>{escape(i['link'])}</link>"
            f'<guid isPermaLink="true">{escape(i["link"])}</guid>'
            f"<pubDate>{format_datetime(i['date'])}</pubDate>"
            "</item>"
        )
    parts.append("</channel></rss>")
    return "".join(parts)


def main():
    items = parse_items(fetch_html())
    if not items:
        print("No items parsed; page structure may have changed.", file=sys.stderr)
        sys.exit(1)  # fail loudly so GitHub Actions doesn't commit an empty feed
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(build_rss(items))
    print(f"Wrote {len(items)} items to {OUT_PATH}")


if __name__ == "__main__":
    main()
