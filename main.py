# --------------------------------------------------------------------
# Script: main.py
# Purpose: Run selected scripts. Save output to S3 buckets
# --------------------------------------------------------------------
RUN_START_DATE = os.environ.get("RUN_START_DATE", "").strip()  # e.g. 2026-11-15
RUN_END_DATE   = os.environ.get("RUN_END_DATE", "").strip()    # e.g. 2026-11-21
OUTPUT_SUFFIX  = os.environ.get("OUTPUT_SUFFIX", "").strip()  # e.g. 2026-11-15_to_2026-11-21

import os
import sys
import subprocess
from pathlib import Path

import boto3


S3_BUCKET = os.environ.get("S3_BUCKET", "congress-s3-20261031")
S3_BASE_PREFIX = os.environ.get("S3_BASE_PREFIX", "data/raw")  # <— match S3 layout

PAIRS = [
    ("apis/fr_api_pres_eo_loop.py", "./data/raw/eo_html", "eo_html"),
    ("apis/fr_api_pres_memo_loop.py", "./data/raw/memo_html", "memo_html"),
]

def upload_dir(s3_client, local_dir: Path, s3_prefix: str):
    local_dir = local_dir.resolve()
    if not local_dir.exists():
        print(f"[WARN] Local output dir not found: {local_dir}", flush=True)
        return

    for p in local_dir.rglob("*"):
        if p.is_dir():
            continue
        rel = p.relative_to(local_dir).as_posix()
        key = f"{s3_prefix.rstrip('/')}/{rel}"
        print(f"[UPLOAD] {p} -> s3://{S3_BUCKET}/{key}", flush=True)
        s3_client.upload_file(str(p), S3_BUCKET, key)

def run_script(script_path: str):
    print(f"\n=== Running {script_path} ===", flush=True)

    child_env = os.environ.copy()

    if RUN_START_DATE and RUN_END_DATE:
        child_env["RUN_START_DATE"] = RUN_START_DATE
        child_env["RUN_END_DATE"] = RUN_END_DATE
        child_env["OUTPUT_SUFFIX"] = f"{RUN_START_DATE}_to_{RUN_END_DATE}"
    # if not set, scheduled naming won’t be enabled (manual test unchanged)

    subprocess.check_call([sys.executable, script_path], env=child_env)

def main():
    s3 = boto3.client("s3")

    for script_path, local_out_dir, out_name in PAIRS:
        run_script(script_path)

        # S3 prefix mirrors existing folder layout.

        s3_prefix = f"{S3_BASE_PREFIX}/{out_name}"
        upload_dir(s3, Path(local_out_dir), s3_prefix)

if __name__ == "__main__":
    main()