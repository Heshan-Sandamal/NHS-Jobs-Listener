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
    filename='C:\\Users\\Lenovo\\PycharmProjects\\trac-jobs-listener\\nhs_scraper.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
# --- Configuration ---
BASE_URL = os.environ["BASE_URL_NHS"]

SEEN_JOBS_FILE = "C:\\Users\\Lenovo\\PycharmProjects\\trac-jobs-listener\\nhs_seen_jobs.pkl"
EMAIL_SENDER = os.environ["EMAIL_SENDER"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
EMAIL_RECEIVER = os.environ["EMAIL_RECEIVER"]
SMTP_SERVER = os.environ["SMTP_SERVER"]
SMTP_PORT = int(os.environ["SMTP_PORT"])

KEYWORDS = ['fellow', 'doctor', 'fy1', 'fy2', 'Foundation Year', 'Surgical', 'Surgery', 'Foundation', "FF1", "FF2",
            "FF3", "SHO"]
pattern = re.compile(r'(' + '|'.join(KEYWORDS) + r')', re.IGNORECASE)

KEYWORDS_NOT_MATCH = ['Registrar', "ST3", "ST 3", "ST3+", "ST4", "ST 4", "ST4+", "ST5", "ST 5", "ST5+", "ST6", "ST 6",
                      "ST6+"]
pattern_NOT_MATCH = re.compile('|'.join(re.escape(word) for word in KEYWORDS_NOT_MATCH))


def get_all_page_urls(start_url, page_urls):
    """Fetch all pagination URLs from the first page."""
    response = requests.get(start_url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'lxml')

    pagination_link = soup.select(
        '#maincontent > div:nth-child(2) > div.nhsuk-grid-column-two-thirds > nav > ul > li.nhsuk-pagination-item--next > a')

    while (len(pagination_link) > 0):
        href = pagination_link[0].get('href')
        if href and "page=" in href:
            full_url = requests.compat.urljoin(BASE_URL, href)
            page_urls.add(full_url)
            return get_all_page_urls(full_url, page_urls)

    page_urls.add(start_url)  # Ensure first page included
    return sorted(page_urls)


def extract_jobs_from_page(url):
    """Extract filtered jobs from a single NHS jobs search results page."""
    print(f"Scraping: {url}")
    response = requests.get(url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")

    job_list = soup.select("ul.nhsuk-list.search-results > li.search-result")
    if not job_list:
        return {}

    jobs = {}
    for li in job_list:
        a = li.select_one("h2 a")
        if not a:
            continue

        title = a.get_text(strip=True)
        link = requests.compat.urljoin(BASE_URL, a["href"])
        link = str(link).split("?")[0]

        # If a regex pattern is supplied, filter titles
        if not pattern.search(title) or bool(pattern_NOT_MATCH.search(title)):
            continue

        # Employer + location
        employer_block = li.select_one('[data-test="search-result-location"] h3')
        employer = employer_block.contents[0].strip() if employer_block else "N/A"
        location = li.select_one('[data-test="search-result-location"] .location-font-size')
        location_text = location.get_text(strip=True) if location else "N/A"

        # Salary, dates, contract, working pattern
        salary = li.select_one('[data-test="search-result-salary"] strong')
        salary_text = salary.get_text(strip=True) if salary else "N/A"

        date_posted = li.select_one('[data-test="search-result-publicationDate"] strong')
        date_posted_text = date_posted.get_text(strip=True) if date_posted else "N/A"

        closing_date = li.select_one('[data-test="search-result-closingDate"] strong')
        closing_date_text = closing_date.get_text(strip=True) if closing_date else "N/A"

        contract_type = li.select_one('[data-test="search-result-jobType"] strong')
        contract_text = contract_type.get_text(strip=True) if contract_type else "N/A"

        working_pattern = li.select_one('[data-test="search-result-workingPattern"] strong')
        working_text = working_pattern.get_text(strip=True) if working_pattern else "N/A"

        # Put everything together
        full_description = (
            f"{title}\n"
            f"Employer: {employer}\n"
            f"Location: {location_text}\n"
            f"Salary: {salary_text}\n"
            f"Date posted: {date_posted_text}\n"
            f"Closing date: {closing_date_text}\n"
            f"Contract: {contract_text}\n"
            f"Working pattern: {working_text}\n"
            f"Link: {link}\n"
        )

        jobs[link] = full_description

    return jobs


def fetch_all_filtered_jobs(START_URL):
    """Get jobs from all paginated pages with filtering."""
    all_jobs = {}
    page_urls = set()
    page_urls.add(START_URL)

    page_urls = get_all_page_urls(START_URL, page_urls)

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
        <h2>🔔 New NHS JObs Listings</h2>
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
    msg['Subject'] = f"New NHS Posts Alert - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_RECEIVER

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)


def main():
    load_dotenv()

    logging.info("Script started. at" + str(datetime.now()))
    URLS = [os.environ["NHS_URL_1"]]

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
