# --------------------------------------------------------------------
# Script: fr_api_pres_eo_loop.py
# Purpose: Use the FederalRegister.gov API to query the federal
#          documents list. Returns executive orders, organized
#          by year and president. Retrieves data from as early
#          as 1994, based on API data availability.

# Input URL: https://www.federalregister.gov/presidential-documents
# Output: /local metadata_presname.jsonl
# --------------------------------------------------------------------

import argparse
import json
import os
import sys
import time
from datetime import datetime

import requests

# -----------------------------
# Helpers
# -----------------------------

DEFAULT_HEADERS = {
    "User-Agent": "fr-eo-api-scraper/0.1 (learning)",
    "Accept": "application/json",
}

API_BASE = "https://www.federalregister.gov/api/v1/documents.json"

PRESIDENTS = [
    "william-j-clinton",
    "george-w-bush",
    "barack-obama",
    "donald-trump",
    "joe-biden",
]


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def year_range(start_year: int, end_year: int):
    for y in range(start_year, end_year + 1):
        yield y

# ---------------------------------------
# Return a set of pre-determined keys
# to support resume/dedup.
# ---------------------------------------
def load_seen_keys(jsonl_path: str, key_field: str):
    seen = set()
    if not os.path.exists(jsonl_path):
        return seen

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            k = obj.get(key_field)
            if k:
                seen.add(k)
    return seen


def fetch_docs_for_query(
    session: requests.Session,
    year: int,
    pres: str | None,
    page: int,
    per_page: int,
    timeout_seconds: float,
    sleep_seconds: float,
    verbose: bool,
):

# --------------------------------------------------
# Minimal query for exploration.
# Uses year/type/president_document_type filters
# --------------------------------------------------
    params = {
        "fields[]": ["title","document_number","executive_order_number","signing_date","publication_date","raw_text_url"],
        "per_page": per_page,
        "page": page,
        "order": "executive_order_number",
        "conditions[publication_date][year]": year,
        "conditions[type][]": "PRESDOCU",
        "conditions[presidential_document_type][]": "executive_order",
    }

    if pres:
        params["conditions[president][]"] = pres

    if verbose:
        print(f"[api] GET {API_BASE}")
        print(f"[api] params: {params}")

    r = session.get(
        API_BASE,
        params=params,
        timeout=timeout_seconds,
        headers={"User-Agent": "Mozilla/5.0 (compatible; eo-scraper/1.0)"},
    )

    if verbose:
        print(f"[api] status={r.status_code}")

    if r.status_code != 200:
        # Print response body to help debug invalid condition params if any
        print("---- API ERROR ----")
        print("url:", r.url)
        print("status:", r.status_code)
        print("response text:", r.text[:4000])
        r.raise_for_status()

    data = r.json()

    # Some FR API endpoints use results; others may use docs.
    docs = data.get("results")
    if docs is None:
        docs = data.get("docs")
    if docs is None:
        docs = []

    if sleep_seconds:
        time.sleep(sleep_seconds)

    return docs, data

# -------------------------------------------------------------------
# Main loop. If --year is passed: select only that year
# Otherwise: discover all available years since 1994, based on API
# availability. Prepare output files per year
# --------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pres", default=None, help="President slug (optional). If omitted, crawl all presidents.")
    ap.add_argument("--year", default=None, type=int, help="Specific year (optional). If omitted, crawl a range.")
    ap.add_argument("--end-year", default=None, type=int, help="End year for range crawl (defaults to current year).")
    ap.add_argument("--out-prefix", default="./data/raw/eo_html", help="Output root folder.")
    ap.add_argument("--sleep-seconds", default=1.0, type=float, help="Delay between page requests.")
    ap.add_argument("--timeout-seconds", default=30.0, type=float, help="HTTP timeout.")
    ap.add_argument("--api-per-page", default=100, type=int, help="per_page for API.")
    ap.add_argument("--cap", default=None, type=int, help="Max records per run (debug safety).")
    ap.add_argument("--max-pages", default=50, type=int, help="Max pages per year (debug safety).")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    presidents = [args.pres] if args.pres else PRESIDENTS
    if args.pres and args.pres not in PRESIDENTS and args.verbose:
        print(f"[warn] --pres={args.pres} not in known list; continuing anyway.")

    if args.end_year is None:
        args.end_year = datetime.utcnow().year

    start_year = 1994
    if args.year is not None:
        years = [args.year]
    else:
        years = list(year_range(start_year, args.end_year))

    key_field = "document_number"

    for pres_slug in presidents:
        for year in years:
            out_dir = os.path.join(args.out_prefix, str(year))
            ensure_dir(out_dir)

            suffix = os.environ.get("OUTPUT_SUFFIX", "").strip()

            if suffix:
                out_path = os.path.join(out_dir, f"metadata_{pres_slug}_{suffix}.jsonl")
            else:
                out_path = os.path.join(out_dir, f"metadata_{pres_slug}.jsonl")

            seen = load_seen_keys(out_path, key_field)

            if args.verbose:
                print(f"[run] pres={pres_slug} year={year}")
                print(f"[run] out={out_path}")
                print(f"[run] seen_keys={len(seen)}")

            total_written = 0

            session = requests.Session()

            for page in range(1, args.max_pages + 1):
                docs, raw_payload = fetch_docs_for_query(
                    session=session,
                    year=year,
                    pres=pres_slug,  # <-- add this
                    page=page,
                    per_page=args.api_per_page,
                    timeout_seconds=args.timeout_seconds,
                    sleep_seconds=args.sleep_seconds,
                    verbose=args.verbose,
                )

                if not docs:
                    if args.verbose:
                        print(f"[page {page}] No docs returned; stopping for year={year}.")
                    break

                if args.verbose:
                    # Print one sample for sanity
                    sample_keys = sorted(list(docs[0].keys())) if docs else []
                    print(f"[page {page}] docs_count={len(docs)} sample_keys={sample_keys}")

                with open(out_path, "a", encoding="utf-8") as f:
                    for doc in docs:
                        # Minimal extraction: only title
                        title = doc.get("title")
                        document_number = doc.get("document_number")
                        executive_order_number = doc.get("executive_order_number")
                        signing_date = doc.get("signing_date")
                        publication_date = doc.get("publication_date")
                        raw_text_url = doc.get("raw_text_url")

                         # Placeholder for URL until I find a valid API field for it
                        fr_document_url = None

                        record = {
                            "fr_document_url": fr_document_url,
                            "president_slug": pres_slug,
                            "year": year,
                            "eo_number": doc.get("executive_order_number"),
                            "title": title,
                            "document_number": document_number,
                            "signing_date": doc.get("signing_date"),
                            "publication_date": doc.get("publication_date"),
                            "federal_register_document_number": doc.get("federal_register_document_number"),
                            "raw_text_url": doc.get("raw_text_url"),
                             }

                        # Dedup on the document number and only when it exists.
                        k = record.get(key_field)
                        if k and k in seen:
                            continue

                        f.write(json.dumps(record, ensure_ascii=False) + "\n")
                        if k:
                            seen.add(k)
                        total_written += 1

                        if args.cap is not None and total_written >= args.cap:
                            if args.verbose:
                                print(f"[cap] Reached cap={args.cap}. Stopping.")
                            break

                if args.cap is not None and total_written >= args.cap:
                    break

            print(f"[done] pres={pres_slug} year={year} wrote={total_written}")


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print(f"[fatal] HTTPError: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[fatal] {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)