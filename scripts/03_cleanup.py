#!/usr/bin/env python3
"""Concatenate pages, strip front/back matter heuristically, segment paragraphs, fix e where possible."""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from utils import PROJECT_ROOT  # noqa: E402

PAGES_DIR = PROJECT_ROOT / "data" / "pages"
OUT_JSON = PROJECT_ROOT / "data" / "french_clean.json"
ERR_JSON = PROJECT_ROOT / "data" / "e_errors_review.json"


def load_pages_ordered() -> str:
    files = sorted(PAGES_DIR.glob("page_*.txt"))
    if not files:
        raise SystemExit(f"No page files in {PAGES_DIR}; run 02_extract_text.py first.")
    parts = []
    for p in files:
        parts.append(p.read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def strip_hyphen_linebreaks(text: str) -> str:
    # "splen-\ndid" -> "splendid"
    return re.sub(r"(\w)-\n(\w)", r"\1\2", text)


def find_novel_start(text: str) -> tuple[str, str]:
    """Drop front matter before first CHAPITRE / strong chapter signal."""
    markers = [
        r"\bCHAPITRE\b",
        r"\bChapitre\b",
        r"\bCHAPTER\b",
        r"\bPREMI[ÈE]RE PARTIE\b",
        r"\bPREMIÈRE\b",
    ]
    best_idx = None
    for pat in markers:
        m = re.search(pat, text, re.IGNORECASE)
        if m and (best_idx is None or m.start() < best_idx):
            best_idx = m.start()
    if best_idx is not None:
        stripped = text[:best_idx]
        return text[best_idx:], stripped
    return text, ""


def strip_back_matter(text: str) -> tuple[str, str]:
    """Heuristic: trim after long colophon-style blocks (TABLE DES MATIÈRES at end, etc.)."""
    # Simple tail cut: last occurrence of common back-matter headers
    cuts = [
        text.rfind("\nTABLE DES MATIÈRES"),
        text.rfind("\nIMPRESSION"),
        text.rfind("\nDépôt légal"),
    ]
    cuts = [c for c in cuts if c > len(text) // 2]
    if cuts:
        idx = min(cuts)
        tail = text[idx:]
        return text[:idx], tail
    return text, ""


def split_paragraphs(body: str) -> list[str]:
    chunks = re.split(r"\n\s*\n+", body)
    return [c.strip() for c in chunks if c.strip()]


def paragraph_chapter(par_text: str) -> tuple[int | None, int | None]:
    ch = None
    pt = None
    m = re.match(r"^(CHAPITRE|Chapitre)\s+([IVXLCDM\d]+)", par_text.strip(), re.I)
    if m:
        # Roman or digit — store as None for roman unless we parse
        ch = 1
    m2 = re.search(r"\bPARTIE\s+([IVX]+|\d+)\b", par_text, re.I)
    if m2:
        pt = 1
    return ch, pt


def build_vocab_e_free(paragraphs: list[str]) -> set[str]:
    vocab: set[str] = set()
    for p in paragraphs:
        if "e" in p.lower():
            continue
        for w in re.findall(r"[A-Za-zÀ-ÿ'-]+", p):
            vocab.add(w.lower())
    return vocab


def try_fix_e_in_word(word: str, vocab: set[str]) -> str | None:
    if "e" not in word and "E" not in word:
        return word
    candidates = []
    for rep in ("é", "è", "ê", "ë"):
        w2 = re.sub(r"[eE]", rep, word, count=1)
        candidates.append(w2)
    for w2 in candidates:
        if w2.lower() in vocab:
            return w2
    return None


def scan_and_fix_paragraph(text: str, vocab: set[str]) -> tuple[str, list[dict]]:
    errors: list[dict] = []
    if "e" not in text and "E" not in text:
        return text, errors

    def repl_word(m: re.Match) -> str:
        w = m.group(0)
        fixed = try_fix_e_in_word(w, vocab)
        if fixed is not None:
            return fixed
        pos = m.start()
        ctx = text[max(0, pos - 20) : pos + 20]
        errors.append(
            {
                "position": pos,
                "context": ctx,
                "suggested_fix": None,
            }
        )
        return w

    # Token-ish replacement on words containing e
    new_text = re.sub(r"[A-Za-zÀ-ÿ]*[eE][A-Za-zÀ-ÿ]*", repl_word, text)
    return new_text, errors


def main() -> None:
    raw = load_pages_ordered()
    raw = strip_hyphen_linebreaks(raw)
    body, front = find_novel_start(raw)
    body, back = strip_back_matter(body)
    if front.strip():
        print(f"Stripped front matter (~{len(front)} chars)")
    if back.strip():
        print(f"Stripped back matter (~{len(back)} chars)")

    paras = split_paragraphs(body)
    vocab = build_vocab_e_free(paras)

    out_paragraphs: list[dict] = []
    all_errors: list[dict] = []
    chapter = 0
    part = 1

    for i, ptext in enumerate(paras, start=1):
        ch_hint, pt_hint = paragraph_chapter(ptext)
        if ch_hint is not None:
            chapter += 1
        if pt_hint is not None:
            part = pt_hint or part
        fixed, errs = scan_and_fix_paragraph(ptext, vocab)
        pid = f"p{i:04d}"
        for e in errs:
            e["paragraph_id"] = pid
        all_errors.extend(errs)
        out_paragraphs.append(
            {
                "id": pid,
                "chapter": chapter if chapter else 1,
                "part": part,
                "text": fixed,
            }
        )

    total_chars = sum(len(p["text"]) for p in out_paragraphs)
    e_count = sum(len(re.findall(r"[eE]", p["text"])) for p in out_paragraphs)

    if all_errors:
        ERR_JSON.parent.mkdir(parents=True, exist_ok=True)
        ERR_JSON.write_text(json.dumps(all_errors, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {ERR_JSON} ({len(all_errors)} items for review)")

    meta = {
        "title": "La Disparition",
        "author": "Georges Perec",
        "source": "archive.org/details/B-001-004-120",
        "total_paragraphs": len(out_paragraphs),
        "total_characters": total_chars,
        "e_count": e_count,
        "extraction_date": datetime.now(timezone.utc).isoformat(),
    }
    doc = {"metadata": meta, "paragraphs": out_paragraphs}
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_JSON}")

    if e_count != 0:
        print(f"VALIDATION FAILED: e_count={e_count} — fix OCR or edit JSON / re-run after manual fixes.")
        sys.exit(1)
    print("Validation OK: zero 'e' in paragraph text.")


if __name__ == "__main__":
    main()
