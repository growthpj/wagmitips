#!/usr/bin/env python3
"""wagmi.tips writer — publishes all approved Google Sheet rows."""

import base64
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from io import BytesIO

import anthropic
from PIL import Image

SHEET_ENDPOINT = os.environ["GOOGLE_SHEET_ENDPOINT"]
SHEET_SECRET = os.environ["GOOGLE_SHEET_API_SECRET"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_OWNER = "growthpj"
GITHUB_REPO = "wagmitips"
GITHUB_BRANCH = "main"
WAGMI_API_KEY = os.environ["WAGMI_ARTICLE_API_KEY"]
SLACK_WEBHOOK = os.environ["SLACK_WEBHOOK_URL"]


def curl_sheet(action):
    url = f"{SHEET_ENDPOINT}?secret={SHEET_SECRET}&action={action}"
    result = subprocess.run(
        ["bash", "-c", f'REDIRECT_URL=$(curl -s "{url}" -w "%{{redirect_url}}" -o /dev/null 2>&1) && curl -s "$REDIRECT_URL"'],
        capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def post_sheet(payload):
    body = json.dumps({**payload, "secret": SHEET_SECRET}).replace("'", "'\\''")
    script = (
        f"REDIRECT_URL=$(curl -s -X POST '{SHEET_ENDPOINT}' "
        f"-H 'Content-Type: application/json' "
        f"-d '{body}' "
        f"-w '%{{redirect_url}}' -o /dev/null 2>&1) && curl -s \"$REDIRECT_URL\""
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def api_call(url, method="GET", headers=None, data=None):
    req = urllib.request.Request(url, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    body = json.dumps(data).encode() if data else None
    with urllib.request.urlopen(req, data=body, timeout=30) as resp:
        return resp.status, json.loads(resp.read())


def write_article(row):
    client = anthropic.Anthropic()
    today = datetime.now(timezone.utc).strftime("%B %-d, %Y")
    prompt = f"""You are an expert AI news journalist for wagmi.tips. Today is {today}.

Article brief:
Title: {row['Article Title']}
Summary: {row['Article Summary']}
Outline: {row['Article Outline']}

Write a fully original 900–1500 word article in semantic HTML. Rules:
- No <h1> tag (title rendered separately)
- Use these section IDs: introduction, background, key-details, why-it-matters, what-this-means, what-happens-next, bottom-line
- No plagiarism — synthesize facts in original wording
- Clear, direct tech-news style. Short paragraphs. No hype.
- US English spelling

Respond with ONLY the HTML content body. No markdown fences, no explanation."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()


def generate_image(title, summary=""):
    prompt = (
        f'Create a clean, premium editorial illustration for this article: "{title}". '
        f"Visually represent the core idea: {summary} "
        "Use a modern flat vector editorial style with strong composition, fewer but larger visual symbols, "
        "generous negative space, subtle depth, and a polished navy-orange tech palette. "
        "Make it sleek, balanced, minimal, and publication-quality. "
        "The image must be 1200 x 630 pixels in a wide landscape format. "
        "Do not include any main headline text inside the artwork. "
        "Avoid clutter, random icons, tiny details, faces, screenshots, or logos. "
        'Important: leave clear empty padding in the bottom-right corner so the text logo "wagmi.tips" '
        "can be placed there cleanly without overlapping key visual elements."
    )
    payload = {
        "model": "gpt-image-1",
        "prompt": prompt,
        "size": "1536x1024",
        "quality": "medium",
        "output_format": "webp"
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/images/generations",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    b64 = data["data"][0]["b64_json"]
    img_bytes = base64.b64decode(b64)

    # Resize to 1200x630
    img = Image.open(BytesIO(img_bytes))
    img = img.convert("RGB")
    img = img.resize((1200, 630), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="WEBP", quality=85)
    return buf.getvalue()


def push_image_to_github(img_bytes, category_slug, slug):
    path = f"images/{category_slug}/{slug}.webp"
    b64 = base64.b64encode(img_bytes).decode()
    data = {"message": f"Add feature image for {slug}", "content": b64, "branch": GITHUB_BRANCH}
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"

    # Check if file exists (need sha to update)
    try:
        status, existing = api_call(url, headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"})
        data["sha"] = existing["sha"]
    except Exception:
        pass

    req = urllib.request.Request(url, data=json.dumps(data).encode(), method="PUT",
                                  headers={"Authorization": f"Bearer {GITHUB_TOKEN}",
                                           "Accept": "application/vnd.github+json",
                                           "X-GitHub-Api-Version": "2022-11-28",
                                           "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())
    raw_url = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}/{path}"
    return raw_url, result


def verify_image(url):
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=15) as resp:
        ct = resp.headers.get("Content-Type", "")
        return resp.status == 200 and "image" in ct


def publish_article(payload):
    req = urllib.request.Request(
        "https://wagmi.tips/api/articles",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-API-Key": WAGMI_API_KEY},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def send_slack(live_url):
    req = urllib.request.Request(
        SLACK_WEBHOOK,
        data=json.dumps({"live_url": live_url}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


def slugify(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:80]


CATEGORY_MAP = {
    "AI Models": "ai-models",
    "Tools & Frameworks": "tools-frameworks",
    "Hardware": "hardware",
    "Open Source": "open-source",
    "Research": "research",
    "Industry": "industry",
    "Tutorials": "tutorials",
}


def pick_category(title, summary):
    client = anthropic.Anthropic()
    opts = "\n".join(f"- {k}" for k in CATEGORY_MAP)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=50,
        messages=[{"role": "user", "content": f"Pick the best category for this article.\nTitle: {title}\nSummary: {summary}\n\nCategories:\n{opts}\n\nReply with ONLY the category name, exactly as written."}]
    )
    cat_name = response.content[0].text.strip()
    cat_slug = CATEGORY_MAP.get(cat_name, "industry")
    return cat_name, cat_slug


def generate_description(title, content):
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": f"Write a 120-160 character SEO meta description for this article.\nTitle: {title}\nContent excerpt: {content[:500]}\n\nReply with ONLY the description, no quotes."}]
    )
    return response.content[0].text.strip()[:160]


def generate_faqs(title, content):
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        messages=[{"role": "user", "content": f"Generate 3 FAQs for this article.\nTitle: {title}\nContent: {content[:1000]}\n\nRespond with ONLY a JSON array of objects with 'question' and 'answer' keys. No markdown."}]
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(raw)


def process_row(row):
    title = row["Article Title"]
    keyword = row["Keyword"]
    row_num = row["rowNumber"]
    print(f"\n--- Processing row {row_num}: {title} ---")

    # Step 2: Write article
    print("Writing article...")
    content = write_article(row)
    print(f"Article: {len(content)} chars")

    # Step 3: Pick category and generate meta
    cat_name, cat_slug = pick_category(title, row["Article Summary"])
    slug = slugify(title)
    description = generate_description(title, content)
    faqs = generate_faqs(title, content)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    word_count = len(content.split())
    read_time = f"{max(1, word_count // 200)} min read"

    # Step 4: Generate image
    print("Generating feature image...")
    img_bytes = generate_image(title, row.get("Article Summary", ""))
    print(f"Image generated: {len(img_bytes)} bytes, 1200x630")

    # Step 5: Push to GitHub
    print("Pushing image to GitHub...")
    raw_url, _ = push_image_to_github(img_bytes, cat_slug, slug)
    print(f"Image URL: {raw_url}")

    # Step 6: Verify image
    print("Verifying image URL...")
    import time
    for attempt in range(5):
        if verify_image(raw_url):
            print("Image verified")
            break
        print(f"  Not yet available, retrying ({attempt+1}/5)...")
        time.sleep(3)
    else:
        raise RuntimeError(f"Image not publicly accessible: {raw_url}")

    # Step 7: Publish article
    print("Publishing article...")
    payload = {
        "slug": slug,
        "title": title,
        "description": description,
        "content": content,
        "heroImageUrl": raw_url,
        "heroImageAlt": keyword,
        "heroImageCaption": title,
        "categoryName": cat_name,
        "categorySlug": cat_slug,
        "authorName": "Wagmi.tips Team",
        "authorSlug": "wagmi-tips-team",
        "authorBio": "We covers AI tools, model updates, and practical technology trends for wagmi.tips.",
        "authorAvatarUrl": None,
        "tags": ["AI", "Artificial Intelligence"],
        "faqs": faqs,
        "relatedArticleSlugs": [],
        "readTime": read_time,
        "isFeatured": False,
        "isPinned": False,
        "metaTitle": f"{title} | wagmi.tips",
        "metaDescription": description,
        "canonicalUrl": None,
        "ogImageUrl": raw_url,
        "noIndex": False,
        "status": "published",
        "publishedAt": now,
    }

    status, resp = publish_article(payload)
    if status == 409:
        slug = slug + "-2"
        payload["slug"] = slug
        status, resp = publish_article(payload)
    if status == 400:
        print(f"400 error: {resp}, retrying with fixed payload...")
        status, resp = publish_article(payload)

    if status not in (200, 201):
        raise RuntimeError(f"Publish failed ({status}): {resp}")

    live_url = f"https://wagmi.tips/{cat_slug}/{slug}"
    print(f"Published: {live_url}")

    # Step 8: Update sheet
    print("Updating Google Sheet...")
    post_sheet({"action": "updateRow", "rowNumber": row_num, "values": {
        "Full Article": "Published",
        "Category": cat_name,
        "URL Slug": slug,
        "Full URL": live_url,
    }})

    # Step 9: Slack
    print("Sending Slack notification...")
    send_slack(live_url)
    print("Slack sent")

    return live_url


def main():
    published = []
    while True:
        result = curl_sheet("getApproved")
        row = result.get("row")
        if not row:
            print("\nNo more approved rows. Done.")
            break
        url = process_row(row)
        published.append(url)

    print(f"\n=== Writer Complete — {len(published)} article(s) published ===")
    for url in published:
        print(f"  {url}")


if __name__ == "__main__":
    main()
