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

load_dotenv()

logging.basicConfig(
    filename='C:\\Users\\Lenovo\\PycharmProjects\\trac-jobs-listener\\healthjobs_scraper.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
# --- Configuration ---
BASE_URL = os.environ["BASE_URL"]

SEEN_JOBS_FILE = "C:\\Users\\Lenovo\\PycharmProjects\\trac-jobs-listener\\seen_jobs.pkl"
EMAIL_SENDER = os.environ["EMAIL_SENDER"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_RECEIVER = os.environ["EMAIL_RECEIVER"]
SMTP_SERVER = os.environ["SMTP_SERVER"]
SMTP_PORT = int(os.environ["SMTP_PORT"])

KEYWORDS = ['fellow', 'doctor', 'fy1', 'fy2', 'Foundation Year', 'Surgical', 'Surgery', 'Foundation', "FF1", "FF2",
            "FF3", "SHO"]
pattern = re.compile(r'(' + '|'.join(KEYWORDS) + r')', re.IGNORECASE)


def get_all_page_urls(start_url):
    """Fetch all pagination URLs from the first page."""
    response = requests.get(start_url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'lxml')

    pagination_links = soup.select('nav.recordset-pager ul.pagination a.page-link[href]')
    page_urls = set()

    for a in pagination_links:
        href = a.get('href')
        if href and "_pg=" in href:
            full_url = requests.compat.urljoin(BASE_URL, href)
            page_urls.add(full_url)

    page_urls.add(start_url)  # Ensure first page included
    return sorted(page_urls)


def extract_jobs_from_page(url):
    """Extract filtered jobs from a single page."""
    print(f"Scraping: {url}")
    response = requests.get(url)
    response.raise_for_status()
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
        except (IndexError, AttributeError):
            continue

        if pattern.search(title):
            link = requests.compat.urljoin(BASE_URL, a['href'])
            jobs[link] = title

            # Job details block
            details_div = li.select_one('div.hj-job-details')
            if not details_div:
                continue

            employer = details_div.select_one('.hj-employername')
            location = details_div.select_one('.hj-locationtown')
            speciality = details_div.select_one('.hj-primaryspeciality')

            # Extract text with fallback
            employer_text = employer.get_text(strip=True) if employer else "N/A"
            location_text = location.get_text(strip=True) if location else "N/A"
            speciality_text = speciality.get_text(strip=True).replace('Speciality:',
                                                                      '').strip() if speciality else "N/A"
            link = requests.compat.urljoin(BASE_URL, a['href'])

            full_description = (
                f"{title}\n"
                f"Employer: {employer_text}\n"
                f"Location: {location_text}\n"
                f"Speciality: {speciality_text}\n"
            )

            jobs[link] = full_description

    return jobs


def fetch_all_filtered_jobs(START_URL):
    """Get jobs from all paginated pages with filtering."""
    all_jobs = {}
    page_urls = get_all_page_urls(START_URL)

    for url in page_urls:
        page_jobs = extract_jobs_from_page(url)
        all_jobs.update(page_jobs)

    return all_jobs


def load_seen_jobs():
    if os.path.exists(SEEN_JOBS_FILE):
        with open(SEEN_JOBS_FILE, 'rb') as f:
            return pickle.load(f)
    return set()


def save_seen_jobs(job_links):
    with open(SEEN_JOBS_FILE, 'wb') as f:
        pickle.dump(set(job_links), f)


def send_email(new_jobs):
    html = """
    <html>
    <body>
        <h2>🔔 New HealthJobsUK Listings</h2>
        <table border="1" cellspacing="0" cellpadding="5" style="border-collapse: collapse; font-family: Arial; font-size: 14px;">
            <thead>
                <tr style="background-color: #f2f2f2;">
                    <th>Title</th>
                    <th>Employer</th>
                    <th>Location</th>
                    <th>Speciality</th>
                    <th>Link</th>
                    <th>Time</th>
                </tr>
            </thead>
            <tbody>
    """

    for link, description in new_jobs.items():
        lines = description.strip().split("\n")
        title = lines[0]
        employer = lines[1].replace("Employer: ", "")
        location = lines[2].replace("Location: ", "")
        speciality = lines[3].replace("Speciality: ", "")

        html += f"""
            <tr>
                <td>{title}</td>
                <td>{employer}</td>
                <td>{location}</td>
                <td>{speciality}</td>
                <td><a href="{link}" target="_blank">View Job</a></td>
                <td>{str(datetime.now())}</td>
            </tr>
        """

    html += """
            </tbody>
        </table>
    </body>
    </html>
    """

    msg = MIMEText(html, 'html')
    msg['Subject'] = f"New HealthJobsUK Posts Alert - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_RECEIVER

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)


def main():
    load_dotenv()

    logging.info("Script started. at" + str(datetime.now()))
    URLS = [os.environ["SCR_URL_1"], os.environ["SCR_URL_2"], os.environ["SCR_URL_3"], os.environ["SCR_URL_4"]]

    all_jobs_for_email = {}
    for url in URLS:
        current_jobs = fetch_all_filtered_jobs(url)
        seen_jobs = load_seen_jobs()

        new_jobs = {lnk: title for lnk, title in current_jobs.items() if lnk not in seen_jobs}

        if new_jobs:
            all_jobs_for_email = all_jobs_for_email | new_jobs
            save_seen_jobs(seen_jobs | current_jobs.keys())

    if (len(all_jobs_for_email) > 0):
        logging.info(f"Found {len(all_jobs_for_email)} new job(s). Sending email...")
        send_email(all_jobs_for_email)
    else:
        logging.info("No new jobs found.")


if __name__ == "__main__":
    main()
