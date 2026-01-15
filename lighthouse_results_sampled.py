import requests
from urllib.parse import urlparse, urlunparse
import subprocess
import csv
import time
import os
import random
import math
from collections import defaultdict

BASE_URL = "https://www.bemidjistate.edu/"
INPUT_CSV = "urls.csv"
OUTPUT_CSV = "lighthouse_results.csv"
SAMPLE_SIZE = 1000

SKIP_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".mp3", ".mp4", ".avi", ".mov"
}

# ---------------------------------------------------------
# URL CLEANING
# ---------------------------------------------------------

def should_skip(url):
    parsed = urlparse(url)
    path = parsed.path.lower()

    if "tel:" in path:
        return True
    if "mailto:" in path:
        return True

    _, ext = os.path.splitext(path)
    return ext in SKIP_EXTENSIONS

def normalize_url(url):
    parsed = urlparse(url)
    cleaned = parsed._replace(query="", fragment="")
    return urlunparse(cleaned)

def load_urls_from_csv(csv_path):
    urls = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in f:
            raw = row.strip()
            if not raw:
                continue
            cleaned = normalize_url(raw)
            if should_skip(cleaned):
                continue
            urls.add(cleaned)
    return list(urls)

# ---------------------------------------------------------
# URL VALIDATION (ONLY FOR SAMPLED URLS)
# ---------------------------------------------------------

def check_url_status(url, timeout=8):
    try:
        resp = requests.head(url, allow_redirects=True, timeout=timeout)
        if resp.status_code >= 400 or resp.status_code == 405:
            resp = requests.get(url, allow_redirects=True, timeout=timeout)
        final_url = resp.url
        status = resp.status_code
        is_redirect = (final_url != url)
        is_404 = (status == 404)
        return final_url, status, is_redirect, is_404
    except Exception:
        return url, None, False, True

def validate_sample(sampled_urls):
    valid = []
    invalid = []
    for url in sampled_urls:
        final_url, status, is_redirect, is_404 = check_url_status(url)
        if is_404 or is_redirect:
            invalid.append(url)
        else:
            valid.append(final_url)
    return valid, invalid

# ---------------------------------------------------------
# IA CATEGORY + DEPTH
# ---------------------------------------------------------

def categorize_url(url):
    path = urlparse(url).path
    parts = [p for p in path.split("/") if p]
    if len(parts) == 0:
        return "root"
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]}/{parts[1]}"

def group_by_category(urls):
    groups = defaultdict(list)
    for url in urls:
        groups[categorize_url(url)].append(url)
    return groups

def url_depth(url):
    parts = [p for p in urlparse(url).path.split("/") if p]
    return len(parts)

def depth_weight(depth):
    return min(depth + 1, 4)

# ---------------------------------------------------------
# STRATIFIED DEPTH-WEIGHTED SAMPLING
# ---------------------------------------------------------

def stratified_depth_weighted_sample(groups, total_sample_size=1000):
    all_urls = sum(len(v) for v in groups.values())
    sample = []

    for category, urls in groups.items():
        proportion = len(urls) / all_urls
        n_cat = max(1, math.floor(proportion * total_sample_size))

        weighted_pool = []
        for url in urls:
            d = url_depth(url)
            w = depth_weight(d)
            weighted_pool.extend([url] * w)

        chosen = random.sample(weighted_pool, min(n_cat, len(weighted_pool)))
        sample.extend(chosen)

    if len(sample) > total_sample_size:
        sample = random.sample(sample, total_sample_size)

    return sample

# ---------------------------------------------------------
# REPLACE INVALID URLS WITH ALTERNATES
# ---------------------------------------------------------

def replace_invalid_urls(valid, invalid, groups, total_needed=1000):
    needed = total_needed - len(valid)
    if needed <= 0:
        return valid[:total_needed]

    replacement_pool = []
    for bad_url in invalid:
        cat = categorize_url(bad_url)
        replacement_pool.extend(groups[cat])

    replacement_pool = [u for u in replacement_pool if u not in valid and u not in invalid]
    random.shuffle(replacement_pool)

    for url in replacement_pool:
        if len(valid) >= total_needed:
            break
        final_url, status, is_redirect, is_404 = check_url_status(url)
        if not is_404 and not is_redirect:
            valid.append(final_url)

    return valid[:total_needed]

# ---------------------------------------------------------
# LIGHTHOUSE
# ---------------------------------------------------------

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
    except Exception:
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
    except Exception:
        return {}

# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main():
    print("Loading URLs from CSV...")
    all_urls = load_urls_from_csv(INPUT_CSV)
    print(f"Loaded {len(all_urls)} raw URLs")

    print("Grouping by IA category...")
    groups = group_by_category(all_urls)
    print(f"Detected {len(groups)} IA categories")

    print("Performing depth-aware stratified sampling...")
    sampled = stratified_depth_weighted_sample(groups, SAMPLE_SIZE)
    print(f"Initial sample size: {len(sampled)}")

    print("Validating sampled URLs...")
    valid, invalid = validate_sample(sampled)
    print(f"Valid: {len(valid)}, Invalid: {len(invalid)}")

    if len(valid) < SAMPLE_SIZE:
        print("Replacing invalid URLs...")
        valid = replace_invalid_urls(valid, invalid, groups, SAMPLE_SIZE)
        print(f"Final valid sample size: {len(valid)}")

    print("Running Lighthouse audits...")
    with open(OUTPUT_CSV, "w", newline="") as csvfile:
        fieldnames = ["url", "performance", "accessibility", "best_practices", "seo"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for url in valid:
            print(f"Auditing: {url}")
            lh_json = run_lighthouse(url)
            if lh_json:
                scores = extract_scores(lh_json)
                writer.writerow(scores)
            time.sleep(5)

if __name__ == "__main__":
    main()
