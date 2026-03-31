#!/usr/bin/env python3
"""Extract text per page from PDF; log pages containing e/E."""

import re
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from utils import PROJECT_ROOT  # noqa: E402

PDF = PROJECT_ROOT / "data" / "raw" / "la_disparition.pdf"
PAGES_DIR = PROJECT_ROOT / "data" / "pages"


def page_has_e(text: str) -> bool:
    return bool(re.search(r"[eE]", text))


def main() -> None:
    if not PDF.is_file():
        print(f"Missing PDF: {PDF}\nRun scripts/01_fetch_pdf.py or add the file manually.")
        sys.exit(1)

    import fitz

    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(PDF)
    bad_pages: list[int] = []
    try:
        total = doc.page_count
        for i in range(total):
            page = doc.load_page(i)
            text = page.get_text("text") or ""
            if not text.strip():
                # Image-only fallback: render + OCR
                try:
                    import pytesseract
                    from PIL import Image
                    import io

                    pix = page.get_pixmap(dpi=300)
                    img = Image.open(io.BytesIO(pix.tobytes("png")))
                    text = pytesseract.image_to_string(img, lang="fra") or ""
                except Exception as e:  # noqa: BLE001
                    print(f"Page {i + 1}: empty text and OCR failed: {e}")
                    text = ""
            n = i + 1
            path = PAGES_DIR / f"page_{n:03d}.txt"
            path.write_text(text, encoding="utf-8")
            e_here = page_has_e(text)
            if e_here:
                bad_pages.append(n)
            print(
                f"page_{n:03d}: chars={len(text)} e_detected={e_here}",
            )
        print("---")
        print(f"Total pages: {total}")
        print(f"Pages with e/E in extracted text: {len(bad_pages)}")
        if bad_pages:
            print(f"Indices: {bad_pages[:50]}{'…' if len(bad_pages) > 50 else ''}")
    finally:
        doc.close()


if __name__ == "__main__":
    main()
