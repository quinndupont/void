#!/usr/bin/env python3
"""Tag explicit main-text boundaries in french_clean.json."""

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from utils import PROJECT_ROOT  # noqa: E402

FRENCH = PROJECT_ROOT / "data" / "french_clean.json"
DEFAULT_PRE_TEXT_IDS = {"p0001", "p0156", "p0157"}


def _ensure_tag_list(para: dict) -> list[str]:
    tags = para.get("tags")
    if tags is None:
        tags = []
        para["tags"] = tags
    elif not isinstance(tags, list):
        tags = [str(tags)]
        para["tags"] = tags
    return tags


def _add_tag(para: dict, tag: str) -> None:
    tags = _ensure_tag_list(para)
    if tag not in tags:
        tags.append(tag)


def _remove_tag(para: dict, tag: str) -> None:
    tags = para.get("tags")
    if isinstance(tags, list):
        para["tags"] = [t for t in tags if t != tag]


def main() -> None:
    if not FRENCH.is_file():
        print(f"Missing {FRENCH}; run 03_cleanup.py first.")
        sys.exit(1)

    doc = json.loads(FRENCH.read_text(encoding="utf-8"))
    paragraphs = doc.get("paragraphs") or []
    if not paragraphs:
        print("No paragraphs in french_clean.json")
        sys.exit(1)

    pre_text_ids = DEFAULT_PRE_TEXT_IDS
    main_indices = [i for i, p in enumerate(paragraphs) if p.get("id") not in pre_text_ids]
    if not main_indices:
        print("No main paragraphs found after excluding pre-text ids.")
        sys.exit(1)

    start_idx = main_indices[0]
    end_idx = main_indices[-1]
    start_id = paragraphs[start_idx]["id"]
    end_id = paragraphs[end_idx]["id"]

    for p in paragraphs:
        _remove_tag(p, "main_start")
        _remove_tag(p, "main_end")
        if p.get("id") in pre_text_ids:
            _add_tag(p, "pre_text")

    _add_tag(paragraphs[start_idx], "main_start")
    _add_tag(paragraphs[end_idx], "main_end")

    FRENCH.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Updated {FRENCH}: tagged pre_text={sorted(pre_text_ids)}, "
        f"main_start={start_id}, main_end={end_id}"
    )


if __name__ == "__main__":
    main()
