#!/usr/bin/env python3
"""Download La Disparition PDF from Archive.org; verify with PyMuPDF page count."""

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from utils import PROJECT_ROOT  # noqa: E402

import requests

ARCHIVE_URL = (
    "https://archive.org/download/B-001-004-120/B-001-004-120.pdf"
)
OUT = PROJECT_ROOT / "data" / "raw" / "la_disparition.pdf"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    print(f"Fetching {ARCHIVE_URL} …")
    r = requests.get(ARCHIVE_URL, timeout=120, stream=True)
    if r.status_code != 200:
        print(
            "Direct download failed (HTTP %s). Archive.org may require lending login.\n"
            "Download manually from https://archive.org/details/B-001-004-120\n"
            "and save as: %s"
            % (r.status_code, OUT)
        )
        sys.exit(1)
    with open(OUT, "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 20):
            if chunk:
                f.write(chunk)
    size = OUT.stat().st_size
    print(f"Saved {OUT} ({size:,} bytes)")

    import fitz  # PyMuPDF

    doc = fitz.open(OUT)
    try:
        n = doc.page_count
        print(f"PyMuPDF page count: {n}")
    finally:
        doc.close()


if __name__ == "__main__":
    main()
