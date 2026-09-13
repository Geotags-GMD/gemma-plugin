#!/usr/bin/env python3
"""
GEMMA Plugin — Secure Google Sheets Integration Script

Secured authentication using Google Cloud Service Account credentials (JSON).
Supports:
1. Fetching email recipient lists dynamically from a Google Sheet.
2. Logging stable/preview release records directly into a Google Sheet.

Usage:
    # Fetch email recipients
    python scripts/release/gsheet_release.py --fetch-emails

    # Log release record
    python scripts/release/gsheet_release.py \
        --log-release \
        --version "3.1.0" \
        --zip-name "gemma-plugin-3.1.0.zip" \
        --actor "user" \
        --repo "GMD-Repository/gemma-plugin"

Environment Variables:
    GCP_SA_KEY              Google Cloud Service Account JSON content (GitHub Secret)
    GSHEET_SPREADSHEET_ID   Target Google Sheet ID (GitHub Secret)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure repo root is on python path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.utils.files import set_github_output

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("gsheet_release")


def get_gspread_client():
    """Authenticate and return gspread client using Service Account key."""
    sa_json = os.environ.get("GCP_SA_KEY") or os.environ.get("GSHEET_CREDENTIALS")
    if not sa_json:
        sa_file = os.environ.get("GCP_SA_KEY_FILE", "references/service_account.json")
        if os.path.exists(sa_file):
            try:
                import gspread
                logger.info("Authenticating via Service Account JSON file: %s", sa_file)
                return gspread.service_account(filename=sa_file)
            except Exception as err:
                logger.error("Failed to authenticate via Service Account file: %s", err)
                return None
        logger.warning("No GCP_SA_KEY or GSHEET_CREDENTIALS environment secret found.")
        return None

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        credentials_info = json.loads(sa_json)
        credentials = Credentials.from_service_account_info(credentials_info, scopes=scopes)
        logger.info("Successfully authenticated via GCP_SA_KEY service account")
        return gspread.authorize(credentials)
    except Exception as err:
        logger.error("Failed to authenticate with Google Service Account: %s", err)
        return None


def fetch_emails(client, spreadsheet_id: str, worksheet_name: str = "email_gemma") -> list[str]:
    """Fetch email recipient list from Google Sheet (Column A, starting from Row 2)."""
    try:
        sh = client.open_by_key(spreadsheet_id)
        try:
            ws = sh.worksheet(worksheet_name)
        except Exception:
            logger.info("Worksheet '%s' not found — using first sheet", worksheet_name)
            ws = sh.get_worksheet(0)

        # Retrieve Column 1 (Column A) values starting from Row 2 (Row 1 is assumed to be Header)
        col_a_values = ws.col_values(1)[1:]

        emails: list[str] = []
        email_regex = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

        for cell in col_a_values:
            cell_str = cell.strip() if cell else ""
            if not cell_str:
                continue

            # Handle comma/semicolon/space separated emails within cells
            parts = [p.strip() for p in re.split(r"[,;\s]+", cell_str) if p.strip()]
            for part in parts:
                if email_regex.match(part) and part not in emails:
                    emails.append(part)

        logger.info("Fetched %d email recipients from Column A (Row 2+) in Google Sheet", len(emails))
        return emails
    except Exception as err:
        logger.error("Error fetching emails from Google Sheet: %s", err)
        return []



def log_release(
    client,
    spreadsheet_id: str,
    version: str,
    zip_name: str,
    actor: str,
    repo: str,
    worksheet_name: str = "Releases",
) -> None:
    """Log release details into Google Sheet."""
    try:
        sh = client.open_by_key(spreadsheet_id)
        try:
            ws = sh.worksheet(worksheet_name)
        except Exception:
            logger.info("Worksheet '%s' not found — creating new worksheet", worksheet_name)
            ws = sh.add_worksheet(title=worksheet_name, rows="500", cols="10")

        all_vals = ws.get_all_values()
        headers = ["Timestamp (UTC)", "Version", "Triggered By", "Zip Package", "Release URL"]
        if not all_vals:
            ws.append_row(headers)

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        release_url = f"https://github.com/{repo}/releases/tag/v{version}"
        row_data = [timestamp, f"v{version}", actor, zip_name, release_url]
        ws.append_row(row_data)
        logger.info("✅ Logged release v%s to Google Sheet sheet '%s'", version, worksheet_name)
    except Exception as err:
        logger.error("Error logging release to Google Sheet: %s", err)


def main() -> None:
    parser = argparse.ArgumentParser(description="Google Sheets Release Integration")
    parser.add_argument("--fetch-emails", action="store_true", help="Fetch recipient emails from Google Sheet")
    parser.add_argument("--log-release", action="store_true", help="Log release entry to Google Sheet")
    parser.add_argument("--version", default="", help="Release version")
    parser.add_argument("--zip-name", default="", help="Plugin zip filename")
    parser.add_argument("--actor", default="github-actions[bot]", help="Release trigger actor")
    parser.add_argument("--repo", default="GMD-Repository/gemma-plugin", help="GitHub repo full name")
    parser.add_argument("--worksheet-emails", default="email_gemma", help="Worksheet name for emails")
    parser.add_argument("--worksheet-log", default="Releases", help="Worksheet name for logs")

    args = parser.parse_args()

    spreadsheet_id = os.environ.get("GSHEET_SPREADSHEET_ID") or os.environ.get("GSPREAD_SPREADSHEET_ID", "")
    if not spreadsheet_id:
        logger.warning("GSHEET_SPREADSHEET_ID secret is not set. Skipping Google Sheet step.")
        return

    client = get_gspread_client()
    if not client:
        logger.warning("Could not obtain Google Sheets API client. Skipping Google Sheet step.")
        return

    if args.fetch_emails:
        emails = fetch_emails(client, spreadsheet_id, worksheet_name=args.worksheet_emails)
        recipients_str = ",".join(emails)

        # Mask each email in GitHub Actions logs to prevent PII leakage.
        # Dynamic step outputs are NOT auto-masked by GitHub (only secrets are).
        # The dawidd6/action-send-mail action logs its inputs, which would
        # otherwise expose all recipient addresses in plaintext.
        if os.environ.get("GITHUB_ACTIONS"):
            for email in emails:
                print(f"::add-mask::{email}")
            if recipients_str:
                print(f"::add-mask::{recipients_str}")

        set_github_output("recipients", recipients_str)

    if args.log_release:
        log_release(
            client=client,
            spreadsheet_id=spreadsheet_id,
            version=args.version,
            zip_name=args.zip_name,
            actor=args.actor,
            repo=args.repo,
            worksheet_name=args.worksheet_log,
        )


if __name__ == "__main__":
    main()
