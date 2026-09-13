"""
File I/O helpers and metadata.txt parsing for the GEMMA release pipeline.

Handles reading/writing metadata.txt (INI-like key=value format),
writing to GITHUB_OUTPUT and GITHUB_STEP_SUMMARY environment files.
"""

from __future__ import annotations

import os
import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


# ── metadata.txt helpers ─────────────────────────────────────────────────────


def read_metadata(path: str | Path) -> dict[str, str]:
    """Read a QGIS metadata.txt file into a dict.

    Parses simple key=value lines. Multi-line values (like `about=` and
    `changelog=`) are read as single values with internal newlines preserved.
    Lines starting with # are comments. Section headers like [general] are skipped.
    """
    path = Path(path)
    content = path.read_text(encoding="utf-8")
    metadata: dict[str, str] = {}
    current_key: str | None = None

    for line in content.splitlines():
        stripped = line.strip()

        # Skip comments and section headers
        if not stripped or stripped.startswith("#") or stripped.startswith("["):
            continue

        # Check for a new key=value pair
        kv_match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)=(.*)", line)
        if kv_match:
            current_key = kv_match.group(1)
            metadata[current_key] = kv_match.group(2).strip()
        elif current_key is not None:
            # Continuation of previous multi-line value
            metadata[current_key] += "\n" + line.rstrip()

    return metadata


def get_metadata_field(metadata: dict[str, str], key: str, default: str = "") -> str:
    """Get a field from parsed metadata, returning default if missing."""
    return metadata.get(key, default).strip()


def read_metadata_raw(path: str | Path) -> str:
    """Read the raw content of metadata.txt."""
    return Path(path).read_text(encoding="utf-8")


def write_metadata_raw(path: str | Path, content: str) -> None:
    """Write raw content back to metadata.txt."""
    Path(path).write_text(content, encoding="utf-8")


# ── GitHub Actions environment helpers ────────────────────────────────────────


def set_github_output(key: str, value: str) -> None:
    """Write a key=value pair to $GITHUB_OUTPUT.

    Safe to call outside GitHub Actions (logs a warning and no-ops).
    Handles multi-line values using the heredoc syntax.
    """
    output_file = os.environ.get("GITHUB_OUTPUT")
    if not output_file:
        logger.warning("GITHUB_OUTPUT not set — skipping output: %s=<redacted %d chars>", key, len(value))
        return

    with open(output_file, "a", encoding="utf-8") as f:
        if "\n" in value:
            # Multi-line value: use heredoc delimiter
            delimiter = "EOF_GEMMA_OUTPUT"
            f.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")
        else:
            f.write(f"{key}={value}\n")

    logger.debug("Set GITHUB_OUTPUT: %s=%s", key, value[:100])


def append_step_summary(content: str) -> None:
    """Append markdown content to the GitHub Actions step summary.

    Safe to call outside GitHub Actions (logs a warning and no-ops).
    """
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_file:
        logger.warning("GITHUB_STEP_SUMMARY not set — printing summary to stdout")
        print(content)
        return

    with open(summary_file, "a", encoding="utf-8") as f:
        f.write(content + "\n")

    logger.debug("Appended to GITHUB_STEP_SUMMARY (%d chars)", len(content))


# ── General file helpers ──────────────────────────────────────────────────────


def ensure_dir(path: str | Path) -> Path:
    """Ensure a directory exists, creating it if necessary."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def read_text(path: str | Path) -> str:
    """Read a text file, returning empty string if it doesn't exist."""
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def write_text(path: str | Path, content: str) -> None:
    """Write text to a file, creating parent directories if needed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    logger.info("Wrote %s (%d bytes)", p, len(content))
