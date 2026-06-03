# wagmi.tips — Claude Brain

Read this file at the start of every session.

This project uses two subagents:

- `research.md` — researches AI news ideas and fills the Google Sheet.
- `writer.md` — writes, images, publishes, and sends Slack updates for approved articles.

The Google Sheet is the source of truth:

https://docs.google.com/spreadsheets/d/1DRCjnhW-1mS2-AsLjtV_ZIQk--9ZvSMhcvIUeUf-AN8/edit?gid=0#gid=0

---

## Core Goal

Build a safe, repeatable AI news publishing workflow for wagmi.tips.

The workflow is:

1. Research agent finds AI news article opportunities.
2. Research agent adds only 3 rows to the Google Sheet per run.
3. Human reviews the rows.
4. Human marks approved articles in Column E with `YES`.
5. Writer agent writes only approved articles.
6. Writer agent generates a feature image.
7. Writer agent pushes the image to GitHub.
8. Writer agent verifies the image exists at a public URL.
9. Writer agent publishes the article through the wagmi.tips API.
10. Writer agent sends a Slack message after successful publishing.

---

## Non-Negotiable Rules

### 1. Ask For Access If Blocked

If Claude or a subagent does not have the access needed to complete a task, stop and ask for the missing access.

Do not guess.
Do not skip the step.
Do not fake completion.

Examples of missing access:

- Cannot read or edit the Google Sheet
- Cannot write to the GitHub repo
- Cannot read or write `.env`
- Missing OpenAI API key
- Missing wagmi.tips article API key
- Missing GitHub token
- Missing Slack webhook or Slack bot token
- Missing article publishing endpoint

When access is missing, ask for the exact value needed.

Example:

```text
I need GITHUB_TOKEN with repo write access before I can upload the generated image.
Please provide it so I can store it in .env.
```

---

### 2. Store Sensitive Values In `.env`

All API keys, tokens, and secrets must be stored in `.env`.

Never hardcode secrets in markdown files, scripts, prompts, article content, or logs.

Sensitive values include:

```text
OPENAI_API_KEY
GITHUB_TOKEN
WAGMI_ARTICLE_API_KEY
WAGMI_API_KEY
ARTICLE_API_KEY
SLACK_WEBHOOK_URL
WAGMITIPS_SLACK_WEBHOOK_URL
SLACK_BOT_TOKEN
GOOGLE_SERVICE_ACCOUNT_JSON
GOOGLE_SHEETS_API_KEY
```

If a required secret is missing:

1. Ask the user for it.
2. Add it to `.env`.
3. Do not print it back in full.
4. Do not expose it in Slack messages, logs, article payloads, or final reports.

---

## Subagent 1: `research.md`

### Purpose

`research.md` is the research agent.

Its job is to research recent AI news and add article ideas to the Google Sheet.

It does not write full articles.
It does not generate images.
It does not publish articles.
It does not send Slack messages.

---

### Research Agent Row Limit

`research.md` must run only 3 rows at a time.

This is mandatory.

If the user does not specify a number, add exactly 3 rows.

If the user asks for more than 3 rows, still add only 3 rows unless the user explicitly changes the system rule.

Do not add 4, 5, or more rows in one run.

If the news cycle is weak, it may add fewer than 3 strong rows.
It must not force weak ideas just to hit the 3-row target.

---

### Research Sheet Output

The research agent fills only these columns:

| Column | Field |
|---|---|
| A | Keyword |
| B | Article Title |
| C | Article Summary |
| D | Article Outline |

Do not add extra columns unless the user asks.
Do not change the sheet structure.
Do not overwrite completed rows unless the user asks.
Append new ideas to the next available empty row.

---

### Research Quality Checks

Before adding an idea to the sheet, `research.md` must verify:

- the story is recent or has a fresh update
- the story has credible sources
- the article idea is not pure speculation
- the proposed title is original
- the summary is not copied from a source article
- the outline gives the writer a clear direction

Use USA English spelling.

---

## Subagent 2: `writer.md`

### Purpose

`writer.md` is the article writing and publishing agent.

Its job is to process approved rows from the Google Sheet and publish completed articles to wagmi.tips.

It writes only approved articles.

---

### Approved Articles Only

`writer.md` must check Column E before writing.

Only process rows where:

```text
Column E = YES
```

Accepted approved values:

```text
YES
Yes
yes
Y
```

Do not process rows where Column E is blank, `NO`, `No`, `no`, or unclear.

If there are no approved rows, stop and report:

```text
No approved article rows found.
```

---

### Writer Input Columns

For approved rows, use:

| Column | Field |
|---|---|
| B | Article Title |
| C | Article Summary |
| D | Article Outline |
| E | Approved |

The writer should base the article on the approved title, summary, and outline.

It must still do fresh source verification before writing.

---

## Writer Publishing Workflow

The writer must follow this sequence exactly:

```text
Check approved row
Research and verify
Write original article
Generate feature image
Push image to GitHub
Verify public image URL
Publish article through wagmi.tips API
Send Slack message
```

Do not reorder these steps.

---

## Image Generation Safety Gate

The writer must generate a feature image for each article using the OpenAI Image Generation API.

Use:

```text
POST https://api.openai.com/v1/images/generations
```

Use the API key from:

```text
OPENAI_API_KEY
```

The image must be:

- 1200x630 px
- suitable for the article title
- clean editorial tech-news style
- free from misleading fake UI, fake charts, or fake screenshots
- free from unnecessary text inside the image

Do not publish an article with:

- no image
- a local image path
- an unverified image URL
- a placeholder image

---

## GitHub Image Upload Gate

After image generation, the writer must push the image to GitHub.

Required `.env` values:

```text
GITHUB_TOKEN
GITHUB_OWNER
GITHUB_REPO
GITHUB_BRANCH
GITHUB_IMAGE_DIR
GITHUB_PUBLIC_BASE_URL
```

If any required GitHub value is missing, stop and ask for it.

The image path should be predictable.

Recommended format:

```text
{GITHUB_IMAGE_DIR}/{categorySlug}/{slug}.webp
```

Example:

```text
public/images/articles/ai-models/claude-opus-4-update.webp
```

Use the GitHub Contents API:

```text
PUT https://api.github.com/repos/{owner}/{repo}/contents/{path}
```

Do not call the wagmi.tips publishing API until the GitHub upload succeeds.

---

## Public Image URL Verification Gate

This is mandatory.

The image must not only be pushed to GitHub.
It must be confirmed to exist at the final public URL.

After GitHub upload, build the final public image URL.

Use this order:

1. If `GITHUB_PUBLIC_BASE_URL` exists, use it.
2. Otherwise, use the raw GitHub URL:

```text
https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}
```

Then verify the image URL.

Preferred check:

```bash
curl -I "$FINAL_IMAGE_URL"
```

Fallback check:

```bash
curl -L "$FINAL_IMAGE_URL" --output /tmp/verify-image.webp
```

Verification must confirm:

- the URL returns a successful response
- the file is publicly reachable
- the content type is an image, such as `image/webp`, `image/png`, or `image/jpeg`
- the file is not empty

If verification fails:

```text
Stop. Do not publish the article.
```

Only after image verification succeeds may the writer use the URL in:

```text
heroImageUrl
ogImageUrl
```

---

## Article Publishing Gate

The writer may only call the wagmi.tips publishing API after all checks pass.

Publishing endpoint:

```text
POST https://wagmi.tips/api/articles
```

Required API key header:

```text
X-API-Key: <secret>
```

Read the API key from `.env`, checking these names:

```text
WAGMI_ARTICLE_API_KEY
WAGMI_API_KEY
ARTICLE_API_KEY
```

If no API key exists, stop and ask for it.

Do not publish until all of these are true:

- approved sheet row found
- article title, summary, and outline extracted
- topic researched and verified
- article written in original wording
- article content formatted as valid semantic HTML
- feature image generated
- feature image pushed to GitHub
- public image URL verified
- `heroImageUrl` uses the verified image URL
- `ogImageUrl` uses the verified image URL
- article API key exists

---

## Slack Notification Gate

Only send a Slack message after the article API confirms successful publishing.

Slack channel:

```text
#wagmitips-articles
```

Look for Slack credentials in `.env`:

```text
SLACK_WEBHOOK_URL
WAGMITIPS_SLACK_WEBHOOK_URL
SLACK_BOT_TOKEN
SLACK_CHANNEL_ID
```

If Slack credentials are missing, ask for them.

Do not send Slack before the article is live.

Message format:

```text
New wagmi.tips article published:
[Article Title]
https://wagmi.tips/<categorySlug>/<slug>
```

---

## Anti-Plagiarism And Reporting Rules

The workflow reports news from other sources.

It must not copy articles.
It must not lightly rewrite source articles.
It must not copy paragraph structure from one source.

The writer must:

- use multiple credible sources
- understand the story first
- write from scratch
- use original headings
- use original paragraph structure
- explain facts in plain English
- attribute claims where needed
- avoid long quotes
- avoid copying headlines or subheadings
- avoid sentence-by-sentence paraphrasing

Before publishing, run this internal check:

1. Is the article structure original?
2. Are the headings original?
3. Are factual claims verified?
4. Is the article written in fresh wording?
5. Does the article avoid close paraphrasing?
6. Would this read like original reporting?

If any answer is no, revise before publishing.

---

## Failure Handling

If a step fails, stop at the failed step.

Do not continue to later steps.

Examples:

- If Google Sheet access fails, do not research or write.
- If no approved rows exist, do not write.
- If image generation fails, do not publish.
- If GitHub upload fails, do not publish.
- If public image verification fails, do not publish.
- If article API returns an error, do not send Slack.
- If Slack fails after publishing, report that the article was published but Slack notification failed.

Always report the blocker clearly.

Use this format:

```text
Blocked at: [step]
Reason: [short reason]
Needed value or action: [what is needed]
No further action was taken.
```

---

## Environment Variable Checklist

Required or commonly used environment variables:

```text
OPENAI_API_KEY=
GITHUB_TOKEN=
GITHUB_OWNER=
GITHUB_REPO=
GITHUB_BRANCH=
GITHUB_IMAGE_DIR=
GITHUB_PUBLIC_BASE_URL=
WAGMI_ARTICLE_API_KEY=
WAGMI_ARTICLE_ENDPOINT=https://wagmi.tips/api/articles
SLACK_WEBHOOK_URL=
SLACK_CHANNEL_ID=
```

Do not commit `.env` to GitHub.
Do not paste `.env` contents into articles, Slack, or final reports.

---

## Final Operating Principle

Be conservative with publishing.

Research can be repeated.
Writing can be revised.
Images can be regenerated.
Publishing should only happen after every required check has passed.

The most important rule:

```text
No verified public image URL = no article publishing API call.
```
