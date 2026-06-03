#!/usr/bin/env python3
"""wagmi.tips researcher — fetches AI news via RSS and writes 3 rows to Google Sheet."""

import json
import os
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import anthropic

SHEET_ENDPOINT = os.environ["GOOGLE_SHEET_ENDPOINT"]
SHEET_SECRET = os.environ["GOOGLE_SHEET_API_SECRET"]

RSS_FEEDS = [
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://venturebeat.com/category/ai/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://huggingface.co/blog/feed.xml",
    "https://feeds.feedburner.com/oreilly/radar",
]


def sheet_get(action):
    """GET request to Apps Script — urllib follows the 302 redirect automatically."""
    url = f"{SHEET_ENDPOINT}?secret={urllib.request.quote(SHEET_SECRET, safe='')}&action={action}"
    req = urllib.request.Request(url, headers={"User-Agent": "wagmitips-researcher/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def sheet_post(payload):
    """POST request to Apps Script — urllib follows 302 to echo URL automatically."""
    body = json.dumps({**payload, "secret": SHEET_SECRET}).encode()
    req = urllib.request.Request(
        SHEET_ENDPOINT,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "wagmitips-researcher/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def fetch_rss(url):
    items = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "wagmitips-researcher/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read()
        root = ET.fromstring(content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for item in root.findall(".//item")[:8]:
            title = item.findtext("title", "").strip()
            desc = (item.findtext("description", "") or "").strip()[:300]
            pub = item.findtext("pubDate", "")
            if title:
                items.append(f"TITLE: {title}\nDESC: {desc}\nDATE: {pub}")
        if not items:
            for entry in root.findall(".//atom:entry", ns)[:8]:
                title = (entry.findtext("atom:title", "", ns) or "").strip()
                summary = (entry.findtext("atom:summary", "", ns) or "").strip()[:300]
                if title:
                    items.append(f"TITLE: {title}\nDESC: {summary}")
    except Exception as e:
        print(f"  Warning: could not fetch {url}: {e}", file=sys.stderr)
    return items


def main():
    # 1. Get existing rows to avoid duplicates
    print("Fetching existing sheet rows...")
    existing = sheet_get("getRows")
    existing_titles = [r.get("Article Title", "") for r in existing.get("rows", [])]
    print(f"Existing rows: {len(existing_titles)}")

    # 2. Fetch RSS feeds
    print("Fetching RSS feeds...")
    all_items = []
    for feed_url in RSS_FEEDS:
        items = fetch_rss(feed_url)
        all_items.extend(items)
        print(f"  {feed_url}: {len(items)} items")

    if not all_items:
        print("WARNING: No RSS items fetched. Proceeding with Claude web knowledge.", file=sys.stderr)

    today = datetime.now(timezone.utc).strftime("%B %Y")
    existing_str = "\n".join(f"- {t}" for t in existing_titles) or "(none)"
    articles_str = "\n\n".join(all_items[:40]) if all_items else "(no RSS items fetched — use your knowledge of recent AI news)"

    # 3. Ask Claude to pick 3 stories and write briefs
    client = anthropic.Anthropic()
    prompt = f"""You are an AI news editor for wagmi.tips. Today is {today}.

Article titles already in our Google Sheet (do NOT duplicate these exact events):
{existing_str}

Recent articles from AI news RSS feeds:
{articles_str}

Your task: pick the 3 strongest, most newsworthy AI stories NOT already covered above.
Only skip a story if it covers the exact same specific event. Different angles on same company are fine.

For each story write:
1. Keyword: main SEO search phrase (short, natural)
2. Article Title: original blog title (do NOT copy the RSS headline)
3. Article Summary: 3-5 sentences — what happened, why it matters, who is affected
4. Article Outline: 6-8 point outline for the writing agent

Respond with ONLY a valid JSON array of exactly 3 objects with keys:
Keyword, Article Title, Article Summary, Article Outline

No markdown fences, no explanation — raw JSON only."""

    print("Asking Claude to select and write 3 article briefs...")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    rows = json.loads(raw)
    if len(rows) != 3:
        print(f"ERROR: Expected 3 rows, got {len(rows)}: {raw}", file=sys.stderr)
        sys.exit(1)

    # 4. Append to sheet
    print("Appending rows to Google Sheet...")
    result = sheet_post({"action": "appendRows", "rows": rows})
    print(f"Sheet response: {json.dumps(result)}")

    if not result.get("success"):
        print(f"ERROR: Sheet rejected rows: {result.get('error')}", file=sys.stderr)
        sys.exit(1)

    print("\n=== Research Complete ===")
    print(f"Added {len(rows)} rows (rows {result['startRow']}–{result['endRow']})")
    for i, row in enumerate(rows, 1):
        print(f"{i}. [{row['Keyword']}] — {row['Article Title']}")


if __name__ == "__main__":
    main()
