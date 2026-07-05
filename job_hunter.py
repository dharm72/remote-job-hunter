"""
Remote Job Hunter for Dharm Vaghasiya
--------------------------------------
Pulls fresh remote job listings from public, no-login job board APIs/feeds,
scores them against Dharm's resume profile, picks the top 10 new matches,
and sends the shortlist via Email and Telegram.

Data sources (all free, public, no scraping-behind-login involved):
  - Remotive API        https://remotive.com/api/remote-jobs
  - Arbeitnow API       https://www.arbeitnow.com/api/job-board-api
  - RemoteOK API        https://remoteok.com/api
  - We Work Remotely    RSS feeds (programming + devops categories)

State: seen_jobs.json keeps track of job IDs already sent, so you never get
the same job twice. Entries older than 45 days are pruned automatically.
"""

import os
import json
import time
import smtplib
import datetime
import xml.etree.ElementTree as ET
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests

# ---------------------------------------------------------------------------
# CONFIG — resume profile (edit this section if your skills/target roles change)
# ---------------------------------------------------------------------------

CANDIDATE_NAME = "Dharm Vaghasiya"

# Skills pulled from the resume/LinkedIn — used for scoring job relevance.
# Weight = how strongly a match on this skill counts.
SKILLS = {
    "python": 3, "django": 3, "fastapi": 3, "frappe": 4, "erpnext": 4,
    "vue": 2, "vue.js": 2, "react": 2, "react.js": 2, "node.js": 1,
    "javascript": 2, "typescript": 2, "sql": 2, "postgresql": 2, "mariadb": 2,
    "mysql": 2, "selenium": 2, "beautifulsoup": 2, "web scraping": 3,
    "rest api": 2, "restful": 1, "aws": 2, "ec2": 1, "s3": 1,
    "pandas": 2, "numpy": 1, "etl": 2, "automation": 3, "shopify": 1,
    "power bi": 1, "metabase": 1, "linux": 1, "git": 1, "jenkins": 1,
    "erp": 3, "supabase": 1,
}

# Preferred job title keywords — extra points if the title contains these.
TITLE_KEYWORDS = {
    "python developer": 6, "python engineer": 6, "backend developer": 5,
    "backend engineer": 5, "full stack": 5, "fullstack": 5,
    "full-stack": 5, "software engineer": 4, "software developer": 4,
    "erpnext": 8, "frappe": 8, "erp developer": 7, "erp consultant": 7,
    "automation engineer": 5, "django developer": 6, "web scraping": 5,
    "rpa": 4, "sde": 3,
}

# Seniority hint — candidate has 4+ yrs experience, so avoid pure junior/intern roles.
NEGATIVE_TITLE_KEYWORDS = {
    "intern": -10, "internship": -10, "junior": -6, "entry level": -6,
    "entry-level": -6, "senior director": -4, "vp of": -8, "chief": -8,
}

MIN_SCORE_THRESHOLD = 6      # jobs below this score are dropped
TOP_N = 10                   # how many jobs to send per run
SEEN_JOBS_FILE = "seen_jobs.json"
SEEN_JOBS_RETENTION_DAYS = 45

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; JobHunterBot/1.0; personal-use-script)"
}

# ---------------------------------------------------------------------------
# FETCHERS — each returns a list of normalized dicts:
# {id, title, company, url, description, tags, source}
# ---------------------------------------------------------------------------

def fetch_remotive():
    jobs = []
    try:
        r = requests.get(
            "https://remotive.com/api/remote-jobs",
            params={"category": "software-dev"},
            headers=HEADERS, timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        for j in data.get("jobs", []):
            jobs.append({
                "id": f"remotive-{j.get('id')}",
                "title": j.get("title", ""),
                "company": j.get("company_name", ""),
                "url": j.get("url", ""),
                "description": (j.get("description", "") or "")[:3000],
                "tags": ", ".join(j.get("tags", []) or []),
                "source": "Remotive",
            })
    except Exception as e:
        print(f"[warn] Remotive fetch failed: {e}")
    return jobs


def fetch_arbeitnow():
    jobs = []
    try:
        r = requests.get(
            "https://www.arbeitnow.com/api/job-board-api",
            headers=HEADERS, timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        for j in data.get("data", []):
            if not j.get("remote", False):
                continue
            jobs.append({
                "id": f"arbeitnow-{j.get('slug')}",
                "title": j.get("title", ""),
                "company": j.get("company_name", ""),
                "url": j.get("url", ""),
                "description": (j.get("description", "") or "")[:3000],
                "tags": ", ".join(j.get("tags", []) or []),
                "source": "Arbeitnow",
            })
    except Exception as e:
        print(f"[warn] Arbeitnow fetch failed: {e}")
    return jobs


def fetch_remoteok():
    jobs = []
    try:
        r = requests.get("https://remoteok.com/api", headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        for j in data:
            if not isinstance(j, dict) or "id" not in j:
                continue  # first element is usually a legal notice, not a job
            jobs.append({
                "id": f"remoteok-{j.get('id')}",
                "title": j.get("position", "") or j.get("title", ""),
                "company": j.get("company", ""),
                "url": j.get("url", ""),
                "description": (j.get("description", "") or "")[:3000],
                "tags": ", ".join(j.get("tags", []) or []),
                "source": "RemoteOK",
            })
    except Exception as e:
        print(f"[warn] RemoteOK fetch failed: {e}")
    return jobs


def fetch_wwr():
    jobs = []
    feeds = [
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    ]
    for feed_url in feeds:
        try:
            r = requests.get(feed_url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            for item in root.findall(".//item"):
                title_full = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                desc = (item.findtext("description") or "")[:3000]
                guid = (item.findtext("guid") or link).strip()
                company, _, title = title_full.partition(": ")
                jobs.append({
                    "id": f"wwr-{guid}",
                    "title": title or title_full,
                    "company": company if title else "",
                    "url": link,
                    "description": desc,
                    "tags": "",
                    "source": "We Work Remotely",
                })
        except Exception as e:
            print(f"[warn] WWR fetch failed for {feed_url}: {e}")
    return jobs


# ---------------------------------------------------------------------------
# SCORING
# ---------------------------------------------------------------------------

def score_job(job):
    text = f"{job['title']} {job['description']} {job['tags']}".lower()
    title_lower = job["title"].lower()
    score = 0

    for skill, weight in SKILLS.items():
        if skill in text:
            score += weight

    for kw, weight in TITLE_KEYWORDS.items():
        if kw in title_lower:
            score += weight

    for kw, weight in NEGATIVE_TITLE_KEYWORDS.items():
        if kw in title_lower:
            score += weight  # weight is already negative

    return score


# ---------------------------------------------------------------------------
# STATE (dedupe across days)
# ---------------------------------------------------------------------------

def load_seen():
    if os.path.exists(SEEN_JOBS_FILE):
        with open(SEEN_JOBS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_seen(seen):
    cutoff = datetime.date.today() - datetime.timedelta(days=SEEN_JOBS_RETENTION_DAYS)
    pruned = {
        jid: date_str for jid, date_str in seen.items()
        if datetime.date.fromisoformat(date_str) >= cutoff
    }
    with open(SEEN_JOBS_FILE, "w") as f:
        json.dump(pruned, f, indent=2)


# ---------------------------------------------------------------------------
# NOTIFICATIONS
# ---------------------------------------------------------------------------

def format_job_block(rank, job):
    return (
        f"{rank}. {job['title']} — {job['company']}\n"
        f"   Source: {job['source']} | Match score: {job['score']}\n"
        f"   Apply: {job['url']}\n"
    )


def send_email(jobs):
    user = os.environ.get("EMAIL_USER")
    password = os.environ.get("EMAIL_PASS")
    to_addr = os.environ.get("EMAIL_TO", user)
    if not user or not password:
        print("[info] Email secrets not set, skipping email.")
        return

    today = datetime.date.today().isoformat()
    subject = f"🎯 {len(jobs)} Remote Job Matches for {CANDIDATE_NAME} — {today}"
    body = f"Good morning! Here are today's top {len(jobs)} remote job matches:\n\n"
    body += "\n".join(format_job_block(i + 1, j) for i, j in enumerate(jobs))
    body += "\n\nGenerated automatically by your Remote Job Hunter script."

    msg = MIMEMultipart()
    msg["From"] = user
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(user, to_addr, msg.as_string())
        print("[info] Email sent.")
    except Exception as e:
        print(f"[error] Email send failed: {e}")


def send_telegram(jobs):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[info] Telegram secrets not set, skipping Telegram.")
        return

    today = datetime.date.today().isoformat()
    header = f"*🎯 {len(jobs)} Remote Job Matches — {today}*\n\n"
    lines = []
    for i, j in enumerate(jobs, 1):
        lines.append(
            f"{i}. *{j['title']}* — {j['company']}\n"
            f"   Score: {j['score']} | {j['source']}\n"
            f"   {j['url']}"
        )
    text = header + "\n\n".join(lines)

    # Telegram messages have a 4096 char limit; split if needed.
    chunks = [text[i:i + 3800] for i in range(0, len(text), 3800)]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in chunks:
        try:
            requests.post(url, data={
                "chat_id": chat_id, "text": chunk,
                "parse_mode": "Markdown", "disable_web_page_preview": True,
            }, timeout=15)
        except Exception as e:
            print(f"[error] Telegram send failed: {e}")
    print("[info] Telegram message(s) sent.")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    print("Fetching jobs from all sources...")
    all_jobs = []
    all_jobs += fetch_remotive()
    time.sleep(1)
    all_jobs += fetch_arbeitnow()
    time.sleep(1)
    all_jobs += fetch_remoteok()
    time.sleep(1)
    all_jobs += fetch_wwr()
    print(f"Fetched {len(all_jobs)} raw listings.")

    seen = load_seen()
    today_str = datetime.date.today().isoformat()

    candidates = []
    for job in all_jobs:
        if job["id"] in seen:
            continue
        s = score_job(job)
        if s >= MIN_SCORE_THRESHOLD:
            job["score"] = s
            candidates.append(job)

    candidates.sort(key=lambda j: j["score"], reverse=True)
    top_jobs = candidates[:TOP_N]

    print(f"{len(candidates)} new matches above threshold; sending top {len(top_jobs)}.")

    if top_jobs:
        send_email(top_jobs)
        send_telegram(top_jobs)
        for job in top_jobs:
            seen[job["id"]] = today_str
        save_seen(seen)
    else:
        print("No new matching jobs today.")

    # Always prune old entries even if no new jobs sent.
    save_seen(seen)


if __name__ == "__main__":
    main()
