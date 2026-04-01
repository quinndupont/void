#!/usr/bin/env python3
"""Evaluate translation files with a local language-ID model."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from utils import PROJECT_ROOT  # noqa: E402

TRANS_DIR = PROJECT_ROOT / "data" / "translations"
OUT_DIR = PROJECT_ROOT / "data" / "language_eval"
SUMMARY_OUT = OUT_DIR / "summary.json"

LANG_CODE_TO_NAME = {
    "en": "english",
    "fr": "french",
    "es": "spanish",
    "de": "german",
    "it": "italian",
    "pt": "portuguese",
    "nl": "dutch",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--judge-model", default="langid.py")
    p.add_argument("--limit", type=int, default=0, help="0 means no limit")
    return p.parse_args()


def clamp_confidence(value: Any) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return 0.0
    if x < 0:
        return 0.0
    if x > 1:
        return 1.0
    return x


def build_langid_identifier():
    import langid

    identifier = langid.langid.LanguageIdentifier.from_modelstring(
        langid.langid.model, norm_probs=True
    )
    return identifier


def judge_language(identifier, text: str) -> tuple[str, float]:
    snippet = (text or "").strip()
    if not snippet:
        return "unknown", 0.0
    code, prob = identifier.classify(snippet)
    language = LANG_CODE_TO_NAME.get(code, code)
    confidence = clamp_confidence(prob)
    return language, confidence


def main() -> None:
    args = parse_args()
    files = sorted(TRANS_DIR.glob("*.json"))
    if not files:
        print(f"No JSON files found in {TRANS_DIR}")
        sys.exit(1)

    identifier = build_langid_identifier()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary_rows: list[dict[str, Any]] = []

    for fp in files:
        doc = json.loads(fp.read_text(encoding="utf-8"))
        model_name = str(doc.get("model") or fp.stem)
        paragraphs = doc.get("paragraphs") or []
        if args.limit > 0:
            paragraphs = paragraphs[: args.limit]

        results: list[dict[str, Any]] = []
        non_english = 0
        french = 0

        for idx, row in enumerate(paragraphs, start=1):
            pid = row.get("id")
            english_text = row.get("english", "")
            language, confidence = judge_language(identifier, english_text)
            is_english = language == "english"
            if not is_english:
                non_english += 1
            if language == "french":
                french += 1
            results.append(
                {
                    "id": pid,
                    "language": language,
                    "confidence": confidence,
                    "is_english": is_english,
                }
            )
            if idx % 25 == 0:
                print(f"  {model_name}: processed {idx}/{len(paragraphs)}")

        out_doc = {
            "source_file": str(fp.relative_to(PROJECT_ROOT)),
            "model": model_name,
            "judge": {
                "provider": "local",
                "model": args.judge_model,
            },
            "totals": {
                "paragraphs": len(results),
                "non_english": non_english,
                "french": french,
                "non_english_rate": round((non_english / len(results)) if results else 0.0, 4),
            },
            "paragraphs": results,
        }
        out_path = OUT_DIR / f"{fp.stem}.lang.json"
        out_path.write_text(json.dumps(out_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        summary_rows.append(
            {
                "model": model_name,
                "file": str(fp.relative_to(PROJECT_ROOT)),
                "paragraphs": len(results),
                "non_english": non_english,
                "french": french,
                "non_english_rate": round((non_english / len(results)) if results else 0.0, 4),
            }
        )
        print(f"{model_name}: non_english={non_english}/{len(results)} french={french}")

    summary_rows.sort(key=lambda r: (-r["non_english_rate"], -r["non_english"], r["model"]))
    summary_doc = {
        "judge": {"provider": "local", "model": args.judge_model},
        "models": summary_rows,
    }
    SUMMARY_OUT.write_text(json.dumps(summary_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {SUMMARY_OUT}")


if __name__ == "__main__":
    main()
