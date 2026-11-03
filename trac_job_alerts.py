import requests
from bs4 import BeautifulSoup
import re
import os
from dotenv import load_dotenv
import pickle
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
import logging
import time

load_dotenv()

# --- Logging ---
logging.basicConfig(
    filename='healthjobs_scraper.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# --- Config ---
BASE_URL = os.environ["BASE_URL"]
SEEN_JOBS_FILE = "seen_jobs.pkl"

EMAIL_SENDER = os.environ["EMAIL_SENDER"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_RECEIVER = os.environ["EMAIL_RECEIVER"]
SMTP_SERVER = os.environ["SMTP_SERVER"]
SMTP_PORT = int(os.environ["SMTP_PORT"])

KEYWORDS = ['fellow', 'doctor', 'fy1', 'fy2', 'Foundation Year', 'Surgical', 'Surgery', 'Foundation', "FF1", "FF2",
            "FF3", "SHO"]
pattern = re.compile(r'(' + '|'.join(KEYWORDS) + r')', re.IGNORECASE)

# --- Session Setup ---
session = requests.Session()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5) AppleWebKit/537.36 Chrome/147.0.0.0 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.healthjobsuk.com/",
    "Connection": "keep-alive"
}


# --- Safe Request ---
def safe_get(url, retries=3):
    for attempt in range(retries):
        try:
            response = session.get(url, headers=HEADERS, timeout=10)
            if response.status_code == 200:
                return response
            logging.warning(f"Retry {attempt+1}: {url} returned {response.status_code}")
        except Exception as e:
            logging.warning(f"Retry {attempt+1} failed: {e}")

        time.sleep(2)

    raise Exception(f"Failed to fetch {url}")


# --- Pagination ---
def get_all_page_urls(start_url):
    response = safe_get(start_url)
    soup = BeautifulSoup(response.text, 'lxml')

    pagination_links = soup.select('nav.recordset-pager ul.pagination a.page-link[href]')
    page_urls = set()

    for a in pagination_links:
        href = a.get('href')
        if href and "_pg=" in href:
            full_url = requests.compat.urljoin(BASE_URL, href)
            page_urls.add(full_url)

    page_urls.add(start_url)
    return sorted(page_urls)


# --- Extract Jobs ---
def extract_jobs_from_page(url):
    logging.info(f"Scraping: {url}")
    response = safe_get(url)
    soup = BeautifulSoup(response.text, 'lxml')

    job_list = soup.select_one('#hj-job-list > ol')
    if not job_list:
        return {}

    jobs = {}

    for li in job_list.find_all('li'):
        a = li.find('a', href=True)
        if not a:
            continue

        try:
            title_div = a.find_all('div')[0].find_all('div')[0]
            title = title_div.get_text(strip=True)
        except:
            continue

        if not pattern.search(title):
            continue

        link = requests.compat.urljoin(BASE_URL, a['href'])

        details_div = li.select_one('div.hj-job-details')

        employer = details_div.select_one('.hj-employername') if details_div else None
        location = details_div.select_one('.hj-locationtown') if details_div else None
        speciality = details_div.select_one('.hj-primaryspeciality') if details_div else None

        employer_text = employer.get_text(strip=True) if employer else "N/A"
        location_text = location.get_text(strip=True) if location else "N/A"
        speciality_text = (
            speciality.get_text(strip=True).replace('Speciality:', '').strip()
            if speciality else "N/A"
        )

        full_description = (
            f"{title}\n"
            f"Employer: {employer_text}\n"
            f"Location: {location_text}\n"
            f"Speciality: {speciality_text}\n"
        )

        jobs[link] = full_description

    return jobs


# --- Fetch All ---
def fetch_all_filtered_jobs(start_url):
    all_jobs = {}
    page_urls = get_all_page_urls(start_url)

    for url in page_urls:
        time.sleep(1)  # avoid blocking
        page_jobs = extract_jobs_from_page(url)
        all_jobs.update(page_jobs)

    return all_jobs


# --- Persistence ---
def load_seen_jobs():
    if os.path.exists(SEEN_JOBS_FILE):
        with open(SEEN_JOBS_FILE, 'rb') as f:
            return pickle.load(f)
    return set()


def save_seen_jobs(job_links):
    with open(SEEN_JOBS_FILE, 'wb') as f:
        pickle.dump(set(job_links), f)


# --- Email ---
def send_email(new_jobs):
    html = """<html><body>
    <h2>🔔 New HealthJobsUK Listings</h2>
    <table border="1" cellpadding="5" cellspacing="0">
    """

    for link, desc in new_jobs.items():
        lines = desc.split("\n")

        html += f"""
        <tr>
            <td>{lines[0]}</td>
            <td>{lines[1].replace("Employer: ", "")}</td>
            <td>{lines[2].replace("Location: ", "")}</td>
            <td>{lines[3].replace("Speciality: ", "")}</td>
            <td><a href="{link}">View</a></td>
        </tr>
        """

    html += "</table></body></html>"

    msg = MIMEText(html, 'html')
    msg['Subject'] = f"New Jobs - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_RECEIVER

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)


# --- Main ---
def main():
    logging.info("Script started")

    # 🔥 Warm-up request (IMPORTANT)
    session.get(BASE_URL, headers=HEADERS)

    URLS = [
        os.environ["SCR_URL_1"],
        os.environ["SCR_URL_2"],
        os.environ["SCR_URL_3"],
        os.environ["SCR_URL_4"],
        os.environ["SCR_URL_5"],
        os.environ["SCR_URL_6"],
        os.environ["SCR_URL_7"],
        os.environ["SCR_URL_8"]
    ]

    seen_jobs = load_seen_jobs()
    all_new_jobs = {}

    for url in URLS:
        try:
            current_jobs = fetch_all_filtered_jobs(url)
            new_jobs = {k: v for k, v in current_jobs.items() if k not in seen_jobs}

            if new_jobs:
                all_new_jobs.update(new_jobs)
                seen_jobs.update(new_jobs.keys())

        except Exception as e:
            logging.error(f"Failed: {url} - {e}")

    if all_new_jobs:
        send_email(all_new_jobs)
        save_seen_jobs(seen_jobs)
        logging.info(f"Sent {len(all_new_jobs)} new jobs")
    else:
        logging.info("No new jobs found")


if __name__ == "__main__":
    main()