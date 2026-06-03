#!/usr/bin/env python3
"""wagmi.tips researcher — fetches AI news via RSS and writes 3 rows to Google Sheet."""

import json
import os
import subprocess
import sys
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
    "https://feeds.feedburner.com/oreilly/radar",
    "https://huggingface.co/blog/feed.xml",
]


def sheet_get(action):
    url = f"{SHEET_ENDPOINT}?secret={SHEET_SECRET}&action={action}"
    result = subprocess.run(
        ["bash", "-c", f'REDIRECT_URL=$(curl -s "{url}" -w "%{{redirect_url}}" -o /dev/null 2>&1) && curl -s "$REDIRECT_URL"'],
        capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def sheet_post(payload):
    body = json.dumps({**payload, "secret": SHEET_SECRET})
    script = (
        f"REDIRECT_URL=$(curl -s -X POST '{SHEET_ENDPOINT}' "
        f"-H 'Content-Type: application/json' "
        f"-d '{body}' "
        f"-w '%{{redirect_url}}' -o /dev/null 2>&1) && curl -s \"$REDIRECT_URL\""
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def fetch_rss(url):
    items = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "wagmitips-bot/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            tree = ET.parse(resp)
        root = tree.getroot()
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        # RSS 2.0
        for item in root.findall(".//item")[:8]:
            title = item.findtext("title", "")
            desc = item.findtext("description", "")
            pub = item.findtext("pubDate", "")
            items.append(f"TITLE: {title}\nDESC: {desc[:300]}\nDATE: {pub}")
        # Atom
        if not items:
            for entry in root.findall(".//atom:entry", ns)[:8]:
                title = entry.findtext("atom:title", "", ns)
                summary = entry.findtext("atom:summary", "", ns)
                items.append(f"TITLE: {title}\nDESC: {summary[:300]}")
    except Exception as e:
        print(f"  Warning: could not fetch {url}: {e}", file=sys.stderr)
    return items


def main():
    # 1. Get existing rows to avoid duplicates
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

    today = datetime.now(timezone.utc).strftime("%B %Y")
    existing_str = "\n".join(f"- {t}" for t in existing_titles) or "(none)"
    articles_str = "\n\n".join(all_items[:40])

    # 3. Ask Claude to pick 3 stories and write briefs
    client = anthropic.Anthropic()
    prompt = f"""You are an AI news editor for wagmi.tips. Today is {today}.

Here are article titles already in our Google Sheet (avoid duplicating these exact events):
{existing_str}

Here are recent articles from AI news RSS feeds:
{articles_str}

Your task: pick the 3 strongest, most newsworthy AI stories NOT already covered above.
Only skip a story if it covers the exact same specific event already in the list.
Different angles on the same company are fine.

For each of the 3 stories, write:
1. Keyword: main SEO search phrase (short, natural language)
2. Article Title: original blog title (do NOT copy the RSS headline)
3. Article Summary: 3-5 sentences covering what happened, why it matters, who is affected
4. Article Outline: 6-8 point outline for the writing agent

Respond with ONLY a JSON array of exactly 3 objects with keys: Keyword, Article Title, Article Summary, Article Outline.
No markdown, no explanation — just the raw JSON array."""

    print("Asking Claude to select and write 3 article briefs...")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0]

    rows = json.loads(raw)
    assert len(rows) == 3, f"Expected 3 rows, got {len(rows)}"

    # 4. Append to sheet
    print("Appending rows to Google Sheet...")
    result = sheet_post({"action": "appendRows", "rows": rows})
    print(f"Sheet response: {json.dumps(result)}")

    if not result.get("success"):
        print(f"ERROR: {result.get('error')}", file=sys.stderr)
        sys.exit(1)

    print("\n=== Research Complete ===")
    print(f"Added {len(rows)} rows (rows {result['startRow']}–{result['endRow']})")
    for i, row in enumerate(rows, 1):
        print(f"{i}. [{row['Keyword']}] — {row['Article Title']}")


if __name__ == "__main__":
    main()
