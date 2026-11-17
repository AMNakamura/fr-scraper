
# --------------------------------------------------------------------
# Script: fr_api_pres.py
# Purpose: Given a president's name, open the federal documents list
#          and return a JSONL with executive orders.
# Input URL: https://www.federalregister.gov/presidential-documents
# Output: /local metadata_presname.jsonl
# To run: python fr_api_pres_eo.py --pres "jimmy-carter"
# --------------------------------------------------------------------

print("Script started")

import os
import json
import time
import hashlib
import argparse
from datetime import datetime, timezone

import requests


# -----------------------------
# Helpers
# -----------------------------

DEFAULT_HEADERS = {
    "User-Agent": "fr-eo-api-scraper/0.1 (learning)",
    "Accept": "application/json",
}


def utc_run_folder_name(dt: datetime | None = None) -> str:
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%d")


def stable_doc_id_from_url(url: str) -> str:
    """
    Stable ID to help dedupe across reruns/runs if needed.
    """
    u = (url or "").strip().encode("utf-8")
    return hashlib.sha256(u).hexdigest()[:32]


def safe_get(d: dict, *keys, default=None):
    """
    Walk nested dicts
    """
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


# -----------------------------
# API querying
# -----------------------------

def fetch_api_results(session: requests.Session, api_url: str, timeout: int = 60, max_retries: int = 5):
    """
    Fetch JSON from the Federal Register API with basic retries/backoff.
    """
    last_err = None
    for attempt in range(max_retries):
        try:
            resp = session.get(api_url, headers=DEFAULT_HEADERS, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_err = e
            sleep_s = min(2 ** attempt, 20)
            time.sleep(sleep_s)

    raise RuntimeError(f"API request failed after {max_retries} retries. Last error: {last_err}")


def extract_records(results_payload: dict) -> list[dict]:
    """
    Convert API payload -> list of records should be in JSONL.

    Note: The Federal Register API commonly returns:
      { "results": [...], "meta": {...} }
    but handle fallbacks.
    """
    records = results_payload.get("results")
    if records is None:
        # Sometimes APIs vary slightly; try other likely keys.
        records = results_payload.get("data") or results_payload.get("items") or []

    if not isinstance(records, list):
        raise RuntimeError(f"Unexpected API 'results' type: {type(records)}")

    output = []
    for doc in records:
        # Try field name variants just in case
        html_url = doc.get("html_url") or doc.get("body_html_url")
        json_url = doc.get("json_url")
        pdf_url = doc.get("pdf_url")

        title = doc.get("title")
        doc_type = doc.get("type") or doc.get("subtype")
        subtype = doc.get("subtype")

        # Look for "type": "Executive Order" for now. Later expand.
        record_type = "Executive Order"  # matches your earlier script’s intent

        # Get the date.
        date_str = doc.get("signing_date") or doc.get("publication_date")

        # Get the doc_id: (prefer json_url then html_url then pdf_url)
        id_source = json_url or html_url or pdf_url or title or ""
        doc_id = stable_doc_id_from_url(id_source)

        rec = {
            "doc_id": doc_id,
            "title": title,
            "type": record_type,
            "date": date_str,
            "url": html_url or json_url,
            # Extra helpful fields (shouldn't break JSONL)
            "executive_order_number": doc.get("executive_order_number"),
            "publication_date": doc.get("publication_date"),
            "pdf_url": pdf_url,
            "subtype": subtype,
            "signing_date": doc.get("signing_date"),
            "disposition_notes": doc.get("disposition_notes"),
        }

        output.append(rec)

    return output


def paginate_api_results(
    session: requests.Session,
    base_api_url: str,
    per_page: int,
    cap: int,
    sleep_seconds: float,
):

    collected = []
    seen_urls = set()

    page = 1
    while True:
        # If base_api_url already contains per_page, page, etc,
        # Append page/per_page.
        joiner = "&" if "?" in base_api_url else "?"
        api_url = f"{base_api_url}{joiner}per_page={per_page}&page={page}"

        payload = fetch_api_results(session, api_url)
        results = extract_records(payload)

        if not results:
            break

        new_count = 0
        for rec in results:
            # de-dupe per run by url if available; fallback to doc_id
            key = rec.get("url") or rec.get("doc_id")
            if key in seen_urls:
                continue
            seen_urls.add(key)
            collected.append(rec)
            new_count += 1

            if len(collected) >= cap:
                return collected[:cap]

        # If API returns fewer than per_page, assume last page.
        if len(results) < per_page:
            break

        page += 1
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    return collected


# -----------------------------
# Output
# -----------------------------

def write_jsonl(records: list[dict], out_path: str):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# -----------------------------
# API querying
# -----------------------------

def build_default_api_url(pres: str):

    return (
        "https://www.federalregister.gov/api/v1/documents.json"
        "?conditions%5Bcorrection%5D=0"
        f"&conditions%5Bpresident%5D={pres}"
        "&conditions%5Bpresidential_document_type%5D=executive_order"
        "&conditions%5Bsearch_type_id%5D=3"
        "&conditions%5Bsigning_date%5D%5Bgte%5D=1981-01-10"
        "&conditions%5Bsigning_date%5D%5Blte%5D=1981-12-31"
        "&conditions%5Bsigning_date%5D%5Byear%5D=1981"
        "&conditions%5Btype%5D%5B%5D=PRESDOCU"
        "&fields%5B%5D=citation"
        "&fields%5B%5D=document_number"
        "&fields%5B%5D=end_page"
        "&fields%5B%5D=html_url"
        "&fields%5B%5D=pdf_url"
        "&fields%5B%5D=type"
        "&fields%5B%5D=subtype"
        "&fields%5B%5D=publication_date"
        "&fields%5B%5D=signing_date"
        "&fields%5B%5D=start_page"
        "&fields%5B%5D=title"
        "&fields%5B%5D=disposition_notes"
        "&fields%5B%5D=executive_order_number"
        "&fields%5B%5D=not_received_for_publication"
        "&fields%5B%5D=full_text_xml_url"
        "&fields%5B%5D=body_html_url"
        "&fields%5B%5D=json_url"
        "&include_pre_1994_docs=true"
        "&maximum_per_page=10000"
        "&order=executive_order"
        "&per_page=10000"
    )


# -----------------------------
# Main
# -----------------------------

def main():
    parser = argparse.ArgumentParser(description="Collect Federal Register Executive Orders via API -> JSONL")
    parser.add_argument("--out-prefix", default="./data/raw/eo", help="Base output directory (local).")
    parser.add_argument("--cap", type=int, default=int(os.getenv("CAP", "100")), help="Max records to collect.")
    parser.add_argument("--per-page", type=int, default=10000, help="API per_page parameter.")
    parser.add_argument("--sleep-seconds", type=float, default=1.0, help="Sleep between paginated requests.")
    parser.add_argument("--api-url", default=None, help="Override API URL.")
    parser.add_argument("--no-pagination", action="store_true", help="Fetch single request only (useful if per_page=10000 is enough).")

    # Parameter-driven president value
    parser.add_argument(
        "--pres",
        default="jimmy-carter",
        help='President slug to use in the Federal Register API (e.g., "jimmy-carter").',
    )

    args = parser.parse_args()

    api_url = args.api_url or build_default_api_url(args.pres)

    run_folder = utc_run_folder_name()

    # Append president name to output filename
    out_path = os.path.join(args.out_prefix, run_folder, f"metadata_single_{args.pres}.jsonl")

    print(f"   Starting FR API collection")
    print(f"   pres: {args.pres}")
    print(f"   out: {out_path}")
    print(f"   cap: {args.cap}")
    print(f"   per-page: {args.per_page}")
    print(f"   pagination: {'off' if args.no_pagination else 'on'}")

    session = requests.Session()

    if args.no_pagination:
        payload = fetch_api_results(session, api_url)
        records = extract_records(payload)
        records = records[: args.cap]
    else:
        records = paginate_api_results(
            session=session,
            base_api_url=api_url.split("&page=")[0],  # prevent double page param if present
            per_page=args.per_page,
            cap=args.cap,
            sleep_seconds=args.sleep_seconds,
        )
        records = records[: args.cap]

    if not records:
        raise RuntimeError(
            "API returned 0 records. \n"
            f"API URL used: {api_url}"
        )

    write_jsonl(records, out_path)
    print(f" Collected {len(records)} records")
    print(f" Wrote to: {out_path}")
    # Folder double check
    print("CWD:", os.getcwd())
    print("ABS OUT:", os.path.abspath(out_path))

if __name__ == "__main__":
    main()