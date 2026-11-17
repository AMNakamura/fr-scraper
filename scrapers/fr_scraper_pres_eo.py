# --------------------------------------------------------------------
# Script: fr_scraper_pres_eo.py
# Purpose: Excluded as unnecessary. Can be used for q quick check,
#          with filters.
#          EO URLs. Default runs get all EOs for all years. However,
#          best to filter by president and year and to include
#          politeness delay to ensure respect of other users
#          and server resources when scraping.
# Input URL: https://www.federalregister.gov/presidential-documents
# Output: /local metadata_presname.jsonl
# To run: python .\scrapers\fr_scraper_pres_eo.py (all presidents all years)
#         python .\scrapers\fr_scraper_pres_eo.py --pres "jimmy-carter" (one pres)
#         python .\scrapers\fr_scraper_pres_eo.py --year "1981" (one year (and pres))
# --------------------------------------------------------------------

print("Script started")

# -----------------------------
# Import packages
# -----------------------------

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from dateutil import parser as date_parser


BASE = "https://www.federalregister.gov"

# -----------------------------
# CrawlConfig dataclass
# configuration container
# -----------------------------

@dataclass
class CrawlConfig:
    out_prefix: str
    sleep_seconds: float
    cap: Optional[int]
    per_request_timeout: int = 30

# -----------------------------
# List of URL slugs to crawl.
# Starts with Jimmy Carter.
# -----------------------------

def president_slugs_since_carter() -> List[str]:
    return [
        "jimmy-carter",
        "ronald-reagan",
        "george-h-w-bush",
        "bill-clinton",
        "george-w-bush",
        "barack-obama",
        "donald-trump",
        "joe-biden",
    ]

# -----------------------------
# Fetch a page.
# Use a shared requests session.
# Return the HTML body as text
# ----------------------------
def fetch_html(session: requests.Session, url: str, timeout: int) -> str:
    r = session.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.text

# ---------------------------------
# Look for patterns like YYYY-#####
# Use the #### as the eo number.
# ---------------------------------

def extract_fr_doc_number_from_url(url: str) -> Optional[str]:
    m = re.search(r"/(\d{4}-\d{5})/", url)
    return m.group(1) if m else None

# -------------------------------------------------------------------
# Get the EO number.
# Look for links like:
#     https://www.federalregister.gov/executive-order/14145
# Try to create a selector in this specific format.
# If that fails, scan all tags where href contains /executive-order/.
# Return the first matching integer.
# --------------------------------------------------------------------

def extract_eo_number_from_page(soup: BeautifulSoup) -> Optional[int]:

    # Try direct href match first
    a = soup.select_one('a[href^="/executive-order/"]')
    if a and a.get("href"):
        m = re.search(r"/executive-order/(\d+)", a["href"])
        if m:
            return int(m.group(1))

    # If multiple links exist or selector missed, scan all matching hrefs
    for tag in soup.select('a[href*="/executive-order/"]'):
        href = tag.get("href", "")
        m = re.search(r"/executive-order/(\d+)", href)
        if m:
            return int(m.group(1))

    return None

# -------------------------------------------------------------------
# Try to parse messy date text (fuzzy parsing) into a Python date.
# Return YYYY-MM-DD string or None if parsing fails.
# --------------------------------------------------------------------

def parse_date_maybe(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        dt = date_parser.parse(s, fuzzy=True)
        return dt.date().isoformat()
    except Exception:
        return None

# -------------------------------------------------------------------
# Get a list of document URLs from the president/year listing by
# pres and year. Load each page like ../executive-orders/<pres_slug>/<year>
# Collects all links whose href begins with /documents/.
# Quickly deduplicate by URL. Then, for each link, store the
#  - document URL (fr_document_url)
#  - anchor text (listing_text) as a human-friendly eyeball clue.
# --------------------------------------------------------------------

def parse_index_page(session: requests.Session, index_url: str, timeout: int) -> List[Dict]:
    print(f"DEBUG parse_index_page() called for: {index_url}")
    html = fetch_html(session, index_url, timeout=timeout)
    soup = BeautifulSoup(html, "lxml")

    results = []
    seen = set()

    for a in soup.select('a[href*="/documents/"]'):
        href = a.get("href", "")
        if href.startswith("http"):
            fr_document_url = href
        else:
            fr_document_url = "https://www.federalregister.gov" + href
        doc_url = f"{BASE}{href}"
        if doc_url in seen:
            continue
        seen.add(doc_url)

        title = a.get_text(" ", strip=True)
        results.append({
            "fr_document_url": doc_url,
            "listing_text": title
        })

    return results

# -------------------------------------------------------------------
# Helper function to parse the text of each document page.
# Get the metadata.
# --------------------------------------------------------------------
def parse_document_page(session: requests.Session, doc_url: str, timeout: int) -> Dict:
    html = fetch_html(session, doc_url, timeout=timeout)
    soup = BeautifulSoup(html, "lxml")

    # h1 title is usually the document title
    h1 = soup.select_one("h1")
    title = h1.get_text(" ", strip=True) if h1 else None

    fr_doc_number = extract_fr_doc_number_from_url(doc_url)
    eo_number = extract_eo_number_from_page(soup)

    # Best-effort date extraction from page text
    signing_date = None
    publication_date = None

    text = soup.get_text("\n", strip=True)

    # Allow permissive regexes - refine later if needed.
    m_sign = re.search(r"Signing Date\s*[:\-]?\s*([A-Za-z0-9,\s]+)", text, flags=re.IGNORECASE)
    if m_sign:
        signing_date = parse_date_maybe(m_sign.group(1))

    m_pub = re.search(r"(Published|Publication Date)\s*[:\-]?\s*([A-Za-z0-9,\s]+)", text, flags=re.IGNORECASE)
    if m_pub:
        publication_date = parse_date_maybe(m_pub.group(2))

    return {
        "fr_document_url": doc_url,
        "title": title,
        "eo_number": eo_number,
        "federal_register_document_number": fr_doc_number,
        "signing_date": signing_date,
        "publication_date": publication_date,
    }

# -------------------------------------------------------------------
# Find years for each president. Some will have more than one combo
# of pres_slug + year. Loop from start_year (e.g., 1981) to now.
# For each year, try to fetch the listing page.
# If the page is available, consider that year valid. Otherwise, skip.
# --------------------------------------------------------------------
def discover_years_for_pres(session: requests.Session, pres_slug: str, start_year: int, end_year: Optional[int] = None) -> List[int]:
    if end_year is None:
        import datetime
        end_year = datetime.datetime.now().year

    years = []
    for y in tqdm(range(start_year, end_year + 1), desc=f"discover years: {pres_slug}"):
        index_url = f"{BASE}/presidential-documents/executive-orders/{pres_slug}/{y}"
        try:
            fetch_html(session, index_url, timeout=30)
        except Exception:
            continue
        years.append(y)
        time.sleep(0.2)
    return years

# -------------------------------------------------------------------
# Main crawl loop for one president (optionally one year)
# Pick the years to crawl. If --year is passed: crawl only that year
# Otherwise: discover all available years since Carter.
# Prepare output file per year
# --------------------------------------------------------------------

def run_for_pres(
    session: requests.Session,
    pres_slug: str,
    year: Optional[int],
    cfg: CrawlConfig,
    start_year: int = 1977
):
    years = [year] if year is not None else discover_years_for_pres(session, pres_slug, start_year=start_year)

    for y in years:
        index_url = f"{BASE}/presidential-documents/executive-orders/{pres_slug}/{y}"

        out_dir = os.path.join(cfg.out_prefix, str(y))
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"metadata_{pres_slug}.jsonl")

        # Resume support
        existing = set()
        if os.path.exists(out_path):
            with open(out_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                        if rec.get("fr_document_url"):
                            existing.add(rec["fr_document_url"])
                    except Exception:
                        pass

        # Stage 1: index crawl
        items = parse_index_page(session, index_url=index_url, timeout=cfg.per_request_timeout)

        written = 0
        for item in tqdm(items, desc=f"{pres_slug} {y} docs"):
            if cfg.cap is not None and written >= cfg.cap:
                break

            doc_url = item["fr_document_url"]
            if doc_url in existing:
                continue

            try:
                meta = parse_document_page(session, doc_url=doc_url, timeout=cfg.per_request_timeout)

                rec = {
                    "fr_document_url": meta.get("fr_document_url"),
                    "president_slug": pres_slug,
                    "year": y,
                    "eo_number": meta.get("eo_number"),
                    "title": meta.get("title"),
                    "signing_date": meta.get("signing_date"),
                    "publication_date": meta.get("publication_date"),
                    "federal_register_document_number": meta.get("federal_register_document_number"),
                    "raw": {
                        "source_index_url": index_url,
                        "listing_text": item.get("listing_text"),
                        "eo_number_url": f"{BASE}/executive-order/{meta.get('eo_number')}" if meta.get("eo_number") else None
                    }
                }

                with open(out_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")

                existing.add(doc_url)
                written += 1
                if cfg.sleep_seconds:
                    time.sleep(cfg.sleep_seconds)

            except Exception as e:
                print(f"[WARN] failed doc {doc_url}: {e}")
                time.sleep(cfg.sleep_seconds)

        print(f"[DONE] {pres_slug} {y}: wrote {written} new records -> {out_path}")

# -------------------------------------------------------------------
# Command-line entry point.
# Crawl only one president and one year. Set the sleep period to add
# a politeness delay.
# --------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pres", default=None, help='President slug (e.g. "jimmy-carter"). If omitted, crawls all since Carter.')
    ap.add_argument("--year", type=int, default=None, help="Optional single year. If omitted, crawls all years for that president.")
    ap.add_argument("--out-prefix", default="./data/raw/eo_html", help="Output base directory")
    ap.add_argument("--sleep-seconds", type=float, default=5.0)
    ap.add_argument("--cap", default=None, type=int, help="Optional max docs written per (pres, year).")
    args = ap.parse_args()

    cfg = CrawlConfig(
        out_prefix=args.out_prefix,
        sleep_seconds=args.sleep_seconds,
        cap=args.cap
    )

# -------------------------------------------------------------------
# Creates one shared HTTP session.
# --------------------------------------------------------------------
    session = requests.Session()

# -------------------------------------------------------------------
# Creates one shared HTTP session.
# --------------------------------------------------------------------

    if args.pres:
        run_for_pres(session, args.pres, args.year, cfg, start_year=1977)
    else:
        for pres_slug in president_slugs_since_carter():
            run_for_pres(session, pres_slug, args.year, cfg, start_year=1977)


if __name__ == "__main__":
    main()