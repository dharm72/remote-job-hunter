"""
Remote Job Hunter for Dharm Vaghasiya
--------------------------------------
Pulls fresh remote job listings from public, no-login job board APIs/feeds,
scores them against Dharm's resume profile, and sends the BEST UP TO 10
matches FROM EACH SOURCE via Email and Telegram (grouped by platform).

Data sources (all free, public, no scraping-behind-login involved):
  - Remotive API        https://remotive.com/api/remote-jobs
  - Arbeitnow API       https://www.arbeitnow.com/api/job-board-api
  - RemoteOK API        https://remoteok.com/api
  - We Work Remotely    RSS feeds (programming + devops categories)
  - Working Nomads API  https://www.workingnomads.com/api/exposed_jobs/
  - Jobicy API          https://jobicy.com/api/v2/remote-jobs
  - Himalayas API       https://himalayas.app/jobs/api
  - Landing.jobs API    https://landing.jobs/api/v1/jobs

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

PER_SOURCE_TOP_N = 10        # how many jobs to send PER SITE, per run
MIN_SANITY_SCORE = 0         # floor to filter out totally irrelevant/negative matches
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


def fetch_working_nomads():
    jobs = []
    try:
        r = requests.get(
            "https://www.workingnomads.com/api/exposed_jobs/",
            headers=HEADERS, timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        for j in data:
            jobs.append({
                "id": f"workingnomads-{j.get('id') or j.get('url')}",
                "title": j.get("title", ""),
                "company": j.get("company_name", ""),
                "url": j.get("url", ""),
                "description": (j.get("description") or "")[:3000],
                "tags": ", ".join(j.get("tags", []) or []),
                "source": "Working Nomads",
            })
    except Exception as e:
        print(f"[warn] Working Nomads fetch failed: {e}")
    return jobs


def fetch_jobicy():
    jobs = []
    try:
        r = requests.get(
            "https://jobicy.com/api/v2/remote-jobs",
            params={"count": 50, "industry": "dev"},
            headers=HEADERS, timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        for j in data.get("jobs", []):
            jobs.append({
                "id": f"jobicy-{j.get('id')}",
                "title": j.get("jobTitle", ""),
                "company": j.get("companyName", ""),
                "url": j.get("url", ""),
                "description": (j.get("jobExcerpt") or "")[:3000],
                "tags": ", ".join(j.get("jobIndustry", []) or []),
                "source": "Jobicy",
            })
    except Exception as e:
        print(f"[warn] Jobicy fetch failed: {e}")
    return jobs


def fetch_himalayas():
    jobs = []
    try:
        r = requests.get(
            "https://himalayas.app/jobs/api",
            headers=HEADERS, timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        for j in data.get("jobs", []):
            jobs.append({
                "id": f"himalayas-{j.get('guid') or j.get('id')}",
                "title": j.get("title", ""),
                "company": (j.get("companyName") or ""),
                "url": j.get("applicationLink", "") or j.get("url", ""),
                "description": (j.get("description") or "")[:3000],
                "tags": ", ".join(j.get("categories", []) or []),
                "source": "Himalayas",
            })
    except Exception as e:
        print(f"[warn] Himalayas fetch failed: {e}")
    return jobs


def fetch_landing_jobs():
    jobs = []
    try:
        r = requests.get(
            "https://landing.jobs/api/v1/jobs",
            params={"remote": "true"},
            headers=HEADERS, timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        listings = data if isinstance(data, list) else data.get("jobs", [])
        for j in listings:
            company = j.get("company", {})
            jobs.append({
                "id": f"landingjobs-{j.get('id') or j.get('slug')}",
                "title": j.get("title", ""),
                "company": company.get("name", "") if isinstance(company, dict) else str(company),
                "url": j.get("url", "") or j.get("share_url", ""),
                "description": (j.get("description") or j.get("body") or "")[:3000],
                "tags": ", ".join(
                    [s.get("name", s) if isinstance(s, dict) else str(s) for s in j.get("skills", []) or []]
                ),
                "source": "Landing.jobs",
            })
    except Exception as e:
        print(f"[warn] Landing.jobs fetch failed: {e}")
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
        f"   Match score: {job['score']}\n"
        f"   Apply: {job['url']}\n"
    )


def send_email(jobs_by_source):
    user = os.environ.get("EMAIL_USER")
    password = os.environ.get("EMAIL_PASS")
    to_addr = os.environ.get("EMAIL_TO", user)
    if not user or not password:
        print("[info] Email secrets not set, skipping email.")
        return

    total = sum(len(v) for v in jobs_by_source.values())
    today = datetime.date.today().isoformat()
    subject = f"🎯 {total} Remote Job Matches for {CANDIDATE_NAME} — {today}"
    body = f"Good morning! Here are today's best matches from each site (up to {PER_SOURCE_TOP_N} per site):\n\n"
    for source, jobs in jobs_by_source.items():
        body += f"=== {source} ({len(jobs)}) ===\n"
        body += "\n".join(format_job_block(i + 1, j) for i, j in enumerate(jobs))
        body += "\n"
    body += "\nGenerated automatically by your Remote Job Hunter script."

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


def send_telegram(jobs_by_source):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[info] Telegram secrets not set, skipping Telegram.")
        return

    today = datetime.date.today().isoformat()
    total = sum(len(v) for v in jobs_by_source.values())
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    # Send one message per source so each platform's block stays readable
    # and no single message blows past Telegram's length limit.
    intro = f"*🎯 {total} Remote Job Matches — {today}*\n(up to {PER_SOURCE_TOP_N} per site)"
    try:
        requests.post(url, data={
            "chat_id": chat_id, "text": intro, "parse_mode": "Markdown",
        }, timeout=15)
    except Exception as e:
        print(f"[error] Telegram intro send failed: {e}")

    for source, jobs in jobs_by_source.items():
        lines = [f"*— {source} ({len(jobs)}) —*"]
        for i, j in enumerate(jobs, 1):
            lines.append(
                f"{i}. *{j['title']}* — {j['company']}\n"
                f"   Score: {j['score']}\n"
                f"   {j['url']}"
            )
        text = "\n\n".join(lines)
        chunks = [text[i:i + 3800] for i in range(0, len(text), 3800)]
        for chunk in chunks:
            try:
                requests.post(url, data={
                    "chat_id": chat_id, "text": chunk,
                    "parse_mode": "Markdown", "disable_web_page_preview": True,
                }, timeout=15)
            except Exception as e:
                print(f"[error] Telegram send failed for {source}: {e}")
    print("[info] Telegram message(s) sent.")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    print("Fetching jobs from all sources...")
    fetchers = [
        fetch_remotive, fetch_arbeitnow, fetch_remoteok, fetch_wwr,
        fetch_working_nomads, fetch_jobicy, fetch_himalayas, fetch_landing_jobs,
    ]
    all_jobs = []
    for fn in fetchers:
        all_jobs += fn()
        time.sleep(1)
    print(f"Fetched {len(all_jobs)} raw listings.")

    seen = load_seen()
    today_str = datetime.date.today().isoformat()

    # Group by source, score, drop already-seen, sort, and take the best
    # PER_SOURCE_TOP_N per platform (not a global top 10).
    by_source = {}
    for job in all_jobs:
        if job["id"] in seen:
            continue
        s = score_job(job)
        if s < MIN_SANITY_SCORE:
            continue
        job["score"] = s
        by_source.setdefault(job["source"], []).append(job)

    jobs_to_send = {}
    for source, jobs in by_source.items():
        jobs.sort(key=lambda j: j["score"], reverse=True)
        top = jobs[:PER_SOURCE_TOP_N]
        if top:
            jobs_to_send[source] = top

    total = sum(len(v) for v in jobs_to_send.values())
    print(f"Sending {total} jobs across {len(jobs_to_send)} sources.")

    if jobs_to_send:
        send_email(jobs_to_send)
        send_telegram(jobs_to_send)
        for jobs in jobs_to_send.values():
            for job in jobs:
                seen[job["id"]] = today_str
    else:
        print("No new matching jobs today.")

    # Always prune old entries even if no new jobs sent.
    save_seen(seen)


if __name__ == "__main__":
    main()
