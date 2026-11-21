# --------------------------------------------------------------------
# Script: main.py
# Purpose: Run selected scripts. Save output to S3 buckets
# --------------------------------------------------------------------

import os
import sys
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import boto3

# ----------------------------------------------------
# Time window configuration
# Compute a rolling window ending at *Sunday midnight PT*.
# end_pt: most recent Sunday 00:00:00 PT (the "belonging to the current run")
# start_pt: end_pt - window_days
# Note: If the job runs exactly at Sunday 00:00 PT, then end_pt
# will be "today's" Sunday 00:00.
# -----------------------
PT = ZoneInfo("America/Los_Angeles")

def compute_sunday_window_pt(now_pt: datetime, window_days: int = 7) -> tuple[datetime, datetime]:

    # weekday(): Mon=0 ... Sun=6
    days_since_sunday = (now_pt.weekday() - 6) % 7
    end_pt = now_pt - timedelta(days=days_since_sunday)
    end_pt = end_pt.replace(hour=0, minute=0, second=0, microsecond=0)

    start_pt = end_pt - timedelta(days=window_days)
    return start_pt, end_pt

now_pt = datetime.now(PT)
start_pt, end_pt = compute_sunday_window_pt(now_pt)

start_date = start_pt.strftime("%Y-%m-%d")
end_date = end_pt.strftime("%Y-%m-%d")

# Suffix used by child scripts to prevent overwriting.
# e.g. 2026-11-14_to_2026-11-21 (based on PT dates)
scheduled_suffix = f"{start_date}_to_{end_date}"

# -----------------------
# AWS / S3 configuration
# -----------------------
S3_BUCKET = os.environ.get("S3_BUCKET", "congress-s3-20261031")
S3_BASE_PREFIX = os.environ.get("S3_BASE_PREFIX", "data/raw")  # <— match S3 layout

# (script_path, local_output_dir, s3_subdir_name)
PAIRS = [
    ("apis/fr_api_pres_eo_loop.py", "./data/raw/eo_html", "eo_html"),
    ("apis/fr_api_pres_memo_loop.py", "./data/raw/memo_html", "memo_html"),
]

# ---------------------------------------------
# Upload all files under local_dir recursively to:
# s3://{S3_BUCKET}/{s3_prefix}/<relative path>
# ----------------------------------------------

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

def run_script(script_path: str, *, scheduled_mode: bool):
    print(f"\n=== Running {script_path} ===", flush=True)

    child_env = os.environ.copy()

    if scheduled_mode:
        # Pass date window + suffix so child loops can:
        # - filter by the rolling window (if implemented in the child)
        # - write non-overwriting filenames via OUTPUT_SUFFIX
        child_env["RUN_START_DATE"] = start_date
        child_env["RUN_END_DATE"] = end_date
        child_env["OUTPUT_SUFFIX"] = scheduled_suffix
    else:
        # Manual/test runs: preserve current behavior (unsuffixed outputs).
        child_env.pop("RUN_START_DATE", None)
        child_env.pop("RUN_END_DATE", None)
        child_env.pop("OUTPUT_SUFFIX", None)

    subprocess.check_call([sys.executable, script_path], env=child_env)

def main():
    # Scheduler should set SCHEDULED_MODE=true for scheduled (auto) runs.
    scheduled_mode = os.environ.get("SCHEDULED_MODE", "").lower() == "true"

    print(f"[INFO] scheduled_mode={scheduled_mode}", flush=True)
    print(f"[INFO] Window PT: start={start_date} end={end_date}", flush=True)
    if scheduled_mode:
        print(f"[INFO] OUTPUT_SUFFIX={scheduled_suffix}", flush=True)

    s3 = boto3.client("s3")

    for script_path, local_out_dir, out_name in PAIRS:
        run_script(script_path, scheduled_mode=scheduled_mode)

        # Mirror existing folder layout in S3.
        s3_prefix = f"{S3_BASE_PREFIX}/{out_name}"
        upload_dir(s3, Path(local_out_dir), s3_prefix)

if __name__ == "__main__":
    main()