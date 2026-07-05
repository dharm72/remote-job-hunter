# Remote Job Hunter — Dharm Vaghasiya

Automatically finds ~10 fresh, relevant remote job listings every day
(Python/Django/FastAPI, ERPNext/Frappe, React/Vue full-stack, and
automation/scraping roles) and sends you the shortlist by Email and
Telegram. Runs free, on a schedule, via GitHub Actions — no server needed.

## What it does
1. Pulls listings from 4 public, no-login job boards: Remotive, Arbeitnow,
   RemoteOK, We Work Remotely.
2. Scores each job against your resume's skills and preferred titles.
3. Filters out anything already sent before (tracked in `seen_jobs.json`).
4. Sends you the top 10 new matches by Email + Telegram every morning
   (08:00 AM IST).
5. **You still click "Apply" yourself** — this does not auto-submit
   applications. See "Why no auto-apply?" below.

---

## One-time setup (~15 minutes)

### 1. Create a GitHub repo
- Go to https://github.com/new
- Name it e.g. `remote-job-hunter`, set it to **Private** (recommended, since
  it'll hold your job search state).
- Upload all files from this folder into the repo (or `git push` them).

### 2. Get a Gmail App Password (for sending email)
Gmail blocks plain-password logins from scripts, so you need an "App Password":
1. Turn on 2-Step Verification on your Google account (if not already):
   https://myaccount.google.com/security
2. Go to https://myaccount.google.com/apppasswords
3. Create a new app password (name it "Job Hunter"), copy the 16-character code.

### 3. Create a Telegram bot (for Telegram alerts)
1. Open Telegram, search for **@BotFather**, send `/newbot`, follow the
   prompts, and copy the **bot token** it gives you.
2. Start a chat with your new bot (search its username, hit Start).
3. Get your **chat ID**: visit
   `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates` in a browser
   after sending your bot any message — you'll see `"chat":{"id": ...}` in
   the JSON response. Copy that number.

### 4. Add secrets to your GitHub repo
In your repo: **Settings → Secrets and variables → Actions → New repository secret**.
Add each of these:

| Secret name | Value |
|---|---|
| `EMAIL_USER` | Your Gmail address |
| `EMAIL_PASS` | The 16-character app password from step 2 |
| `EMAIL_TO` | Where you want the daily email sent (can be same as EMAIL_USER) |
| `TELEGRAM_BOT_TOKEN` | Bot token from step 3 |
| `TELEGRAM_CHAT_ID` | Chat ID from step 3 |

### 5. Test it
Go to the **Actions** tab in your repo → **Daily Remote Job Search** →
**Run workflow** (this is the `workflow_dispatch` trigger, lets you test
without waiting for the schedule). Check your email/Telegram in ~1 minute.

That's it — it will now run automatically every day at 08:00 AM IST.

---

## Adjusting the schedule
Edit `.github/workflows/daily-job-search.yml`, the line:
```yaml
- cron: "30 2 * * *"
```
This is in UTC. Example: for 07:00 AM IST, use `"30 1 * * *"`.

## Adjusting your skill/role profile
Open `job_hunter.py` and edit the `SKILLS`, `TITLE_KEYWORDS`, and
`NEGATIVE_TITLE_KEYWORDS` dictionaries near the top — these drive scoring.
Raise `MIN_SCORE_THRESHOLD` if you're getting too many loosely-relevant jobs,
lower it if you're getting too few.

## Why no auto-apply?
Actually submitting applications on LinkedIn/Indeed/company ATS portals
requires logging into your accounts, and these sites use CAPTCHAs and
bot-detection specifically to block automated submissions — doing so also
risks your account getting flagged. Instead, this tool gets you 90% of the
way (finding + ranking + link), so your daily effort is just reviewing 10
pre-qualified links and clicking Apply — usually 15–20 minutes/day instead
of hours of searching.

## Optional next step: AI-drafted cover letters
If you want, I can extend this script to auto-draft a tailored cover
letter/summary for each of the 10 jobs using the Claude API (needs an
Anthropic API key added as another secret). Just ask and I'll add it.
