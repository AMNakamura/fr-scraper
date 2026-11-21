# --------------------------------------------------------------------
# Script: main.py
# Purpose: Run selected scripts. Save output to S3 buckets
# --------------------------------------------------------------------


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
    subprocess.check_call([sys.executable, script_path])

def main():
    s3 = boto3.client("s3")

    for script_path, local_out_dir, out_name in PAIRS:
        run_script(script_path)

        # S3 prefix mirrors existing folder layout.

        s3_prefix = f"{S3_BASE_PREFIX}/{out_name}"
        upload_dir(s3, Path(local_out_dir), s3_prefix)

if __name__ == "__main__":
    main()