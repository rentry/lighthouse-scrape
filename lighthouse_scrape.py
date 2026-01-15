import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse
import subprocess
import csv
import time
import os
import xml.etree.ElementTree as ET

BASE_URL = "https://www.bemidjistate.edu/"
SITEMAP_URL = urljoin(BASE_URL, "sitemap.xml")
OUTPUT_CSV = "lighthouse_results.csv"
VISITED = set()

# Extensions to ignore
SKIP_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".mp3", ".mp4", ".avi", ".mov"
}

def should_skip(url):
    """Return True if URL ends with a file extension we want to ignore,
    or if it is a telephone or mailto link."""
    parsed = urlparse(url)
    path = parsed.path.lower()

    # Skip tel: links anywhere in the path
    if "tel:" in path:
        return True

    # Skip mailto: links
    if "mailto:" in path:
        return True

    # Skip file extensions
    _, ext = os.path.splitext(path)
    return ext in SKIP_EXTENSIONS

def normalize_url(url):
    """Remove fragments (#) and query parameters (?) from a URL."""
    parsed = urlparse(url)
    cleaned = parsed._replace(query="", fragment="")
    return urlunparse(cleaned)

def parse_sitemap(url, collected=None):
    """Recursively parse sitemap.xml and return a set of URLs."""
    if collected is None:
        collected = set()

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        root = ET.fromstring(response.text)

        namespace = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}

        # Case 1: sitemap index
        for sitemap in root.findall("ns:sitemap", namespace):
            loc = sitemap.find("ns:loc", namespace)
            if loc is not None:
                parse_sitemap(loc.text.strip(), collected)

        # Case 2: regular sitemap
        for url_tag in root.findall("ns:url", namespace):
            loc = url_tag.find("ns:loc", namespace)
            if loc is not None:
                cleaned = normalize_url(loc.text.strip())
                if not should_skip(cleaned):
                    collected.add(cleaned)

    except Exception as e:
        print(f"Error parsing sitemap {url}: {e}")

    return collected

def get_internal_links(url):
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        links = set()

        for a_tag in soup.find_all("a", href=True):
            href = urljoin(url, a_tag['href'])
            href = normalize_url(href)

            # Only internal links
            if urlparse(href).netloc != urlparse(BASE_URL).netloc:
                continue

            # Skip unwanted file types and tel/mailto links
            if should_skip(href):
                continue

            links.add(href)

        return links

    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return set()

def crawl_site(start_url):
    # Load URLs from sitemap first
    sitemap_urls = parse_sitemap(SITEMAP_URL)
    print(f"Loaded {len(sitemap_urls)} URLs from sitemap.xml")

    to_visit = list(sitemap_urls)
    to_visit.append(start_url)

    while to_visit:
        current = to_visit.pop()
        if current not in VISITED:
            VISITED.add(current)
            print(f"Crawling: {current}")
            new_links = get_internal_links(current)
            to_visit.extend(new_links - VISITED)

def run_lighthouse(url):
    try:
        result = subprocess.run([
            "lighthouse", url,
            "--quiet",
            "--chrome-flags='--headless'",
            "--output=json",
            "--output-path=stdout"
        ], capture_output=True, text=True, timeout=120)
        return result.stdout
    except Exception as e:
        print(f"Error running Lighthouse on {url}: {e}")
        return None

def extract_scores(lighthouse_json):
    import json
    try:
        data = json.loads(lighthouse_json)
        categories = data.get("categories", {})
        return {
            "url": data.get("finalUrl", None),
            "performance": categories.get("performance", {}).get("score", None),
            "accessibility": categories.get("accessibility", {}).get("score", None),
            "best_practices": categories.get("best-practices", {}).get("score", None),
            "seo": categories.get("seo", {}).get("score", None)
        }
    except Exception as e:
        print(f"Error parsing Lighthouse JSON: {e}")
        return {}

def main():
    crawl_site(BASE_URL)

    with open(OUTPUT_CSV, "w", newline="") as csvfile:
        fieldnames = ["url", "performance", "accessibility", "best_practices", "seo"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for url in VISITED:
            print(f"Auditing: {url}")
            lh_json = run_lighthouse(url)
            if lh_json:
                scores = extract_scores(lh_json)
                writer.writerow(scores)
            time.sleep(5)

if __name__ == "__main__":
    main()
