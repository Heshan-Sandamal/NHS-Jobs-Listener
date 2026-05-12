import re
import os
import time
import pickle
import smtplib
import logging
from datetime import datetime
from email.mime.text import MIMEText
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

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

KEYWORDS = [
    'fellow', 'doctor', 'Surgical', 'Surgery', "Trauma",
    "SHO", "Orthopaedic", "ST3", "ST4", "ST5",
    "ST6", "ST7", "ST8", "Registrar"
]

pattern = re.compile(r'(' + '|'.join(KEYWORDS) + r')', re.IGNORECASE)


# --- Persistence ---
def load_seen_jobs():
    if os.path.exists(SEEN_JOBS_FILE):
        with open(SEEN_JOBS_FILE, 'rb') as f:
            return pickle.load(f)
    return set()


def save_seen_jobs(job_links):
    with open(SEEN_JOBS_FILE, 'wb') as f:
        pickle.dump(set(job_links), f)


# --- COOKIE HANDLER (NEW FIX) ---
def accept_cookies(page):
    try:
        # Most common UK cookie buttons
        selectors = [
            "button:has-text('Accept')",
            "button:has-text('Accept all')",
            "button:has-text('I accept')",
            "text=Accept all cookies",
            "#onetrust-accept-btn-handler"
        ]

        for selector in selectors:
            try:
                btn = page.locator(selector)
                if btn.count() > 0:
                    btn.first.click(timeout=3000)
                    logging.info(f"Cookie accepted using: {selector}")
                    time.sleep(1)
                    return
            except:
                pass

    except Exception as e:
        logging.warning(f"Cookie handling failed: {e}")


# --- Extract Jobs ---
def extract_jobs_from_html(html):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    job_list = soup.select_one('#hj-job-list > ol')

    if not job_list:
        return {}

    jobs = {}

    for li in job_list.find_all('li'):
        a = li.find('a', href=True)
        if not a:
            continue

        try:
            title = a.find_all('div')[0].find_all('div')[0].get_text(strip=True)
        except:
            continue

        if not pattern.search(title):
            continue

        link = BASE_URL + a['href']

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


# --- Pagination ---
def get_all_pages(page):
    links = page.query_selector_all('nav.recordset-pager a.page-link')
    urls = set()

    for l in links:
        href = l.get_attribute("href")
        if href and "_pg=" in href:
            urls.add(BASE_URL + href)

    return sorted(urls)


# --- Scrape ---
def scrape_jobs(playwright, start_urls):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    all_jobs = {}

    # warm up
    page.goto(BASE_URL, timeout=60000)
    time.sleep(2)

    accept_cookies(page)   # 🔥 FIX ADDED HERE

    for start_url in start_urls:
        logging.info(f"Opening {start_url}")

        page.goto(start_url, timeout=60000)
        time.sleep(2)

        accept_cookies(page)  # 🔥 ensure popup handled per page

        # safer wait than ID selector
        try:
            page.wait_for_selector("#hj-job-list", timeout=20000)
            page.wait_for_selector("li.hj-job", timeout=20000)
        except:
            logging.warning(f"Job list not found: {start_url}")
            continue

        page_urls = get_all_pages(page)
        page_urls.append(start_url)

        for url in page_urls:
            logging.info(f"Scraping page: {url}")

            page.goto(url, timeout=60000)
            time.sleep(2)

            accept_cookies(page)

            try:
                page.wait_for_selector("#hj-job-list", timeout=20000)
                page.wait_for_selector("li.hj-job", timeout=20000)
            except:
                logging.warning(f"Skipping page (no content): {url}")
                continue

            html = page.content()
            jobs = extract_jobs_from_html(html)

            all_jobs.update(jobs)

            time.sleep(1)

    browser.close()
    return all_jobs


# --- Email ---
def send_email(new_jobs):
    html = "<html><body><h2>🔔 New Jobs</h2><table border='1'>"

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
    msg['Subject'] = f"New Jobs - {datetime.now()}"
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_RECEIVER

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)


# --- Main ---
def main():
    logging.info("Script started")

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

    with sync_playwright() as p:
        all_jobs = scrape_jobs(p, URLS)

    new_jobs = {k: v for k, v in all_jobs.items() if k not in seen_jobs}

    if new_jobs:
        send_email(new_jobs)
        save_seen_jobs(seen_jobs.union(new_jobs.keys()))
        logging.info(f"Sent {len(new_jobs)} jobs")
    else:
        logging.info("No new jobs found")


if __name__ == "__main__":
    main()