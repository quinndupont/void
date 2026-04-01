#!/usr/bin/env python3
"""Aggregate e-metrics; write data/scores.json and site/data.json."""

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from utils import PROJECT_ROOT  # noqa: E402

FRENCH = PROJECT_ROOT / "data" / "french_clean.json"
TRANS_DIR = PROJECT_ROOT / "data" / "translations"
SCORES_OUT = PROJECT_ROOT / "data" / "scores.json"
SITE_DATA = PROJECT_ROOT / "site" / "data.json"
LANG_SUMMARY = PROJECT_ROOT / "data" / "language_eval" / "summary.json"
LANG_EVAL_DIR = PROJECT_ROOT / "data" / "language_eval"


def load_french_map() -> dict:
    data = json.loads(FRENCH.read_text(encoding="utf-8"))
    return {p["id"]: p for p in data["paragraphs"]}


def load_all_translations() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in TRANS_DIR.glob("*.json"):
        doc = json.loads(p.read_text(encoding="utf-8"))
        out[doc["model"]] = doc
    return out


def first_failure(rows: list[dict]) -> str | None:
    for r in sorted(rows, key=lambda x: x["id"]):
        if r.get("e_count", 0) > 0:
            return r["id"]
    return None


def default_model_colors(models: list[str]) -> dict[str, str]:
    palette = [
        "#B85C3A",
        "#3A6B8F",
        "#6B8F3A",
        "#8F3A6B",
        "#6B3A8F",
        "#3A8F6B",
        "#8F6B3A",
        "#4A6FA5",
        "#A56F4A",
        "#5A4FA6",
    ]
    return {m: palette[i % len(palette)] for i, m in enumerate(sorted(models))}


def build_site_json(
    meta: dict,
    french_by_id: dict,
    translations: dict[str, dict],
    scores_models: list[dict],
) -> dict:
    models = [s["name"] for s in scores_models]
    by_para: dict[str, dict] = {}
    lang_rows_by_model: dict[str, dict[str, dict]] = {}
    for path in LANG_EVAL_DIR.glob("*.lang.json"):
        lang_doc = json.loads(path.read_text(encoding="utf-8"))
        model_name = str(lang_doc.get("model") or path.stem.replace(".lang", ""))
        para_map: dict[str, dict] = {}
        for row in lang_doc.get("paragraphs", []):
            pid = row.get("id")
            if pid:
                para_map[str(pid)] = row
        lang_rows_by_model[model_name] = para_map
    for mid in models:
        doc = translations[mid]
        for row in doc["paragraphs"]:
            pid = row["id"]
            if pid not in by_para:
                fp = french_by_id.get(pid)
                by_para[pid] = {
                    "id": pid,
                    "chapter": (fp or {}).get("chapter", 1),
                    "french": (fp or {}).get("text", row.get("french", "")),
                    "translations": {},
                }
            by_para[pid]["translations"][mid] = {
                "text": row.get("english", ""),
                "e_count": row.get("e_count", 0),
                "is_failure": (
                    lang_rows_by_model.get(mid, {}).get(pid, {}).get("is_english") is False
                    if pid in lang_rows_by_model.get(mid, {})
                    else None
                ),
            }
    pass_rates = {s["name"]: s.get("pass_rate", 0) for s in scores_models}
    best = max(models, key=lambda m: pass_rates.get(m, 0)) if models else None
    lang_by_model: dict[str, dict] = {}
    if LANG_SUMMARY.is_file():
        lang_doc = json.loads(LANG_SUMMARY.read_text(encoding="utf-8"))
        for row in lang_doc.get("models", []):
            if isinstance(row, dict) and row.get("model"):
                lang_by_model[str(row["model"])] = row

    model_stats = {}
    for s in scores_models:
        name = s["name"]
        lang = lang_by_model.get(name, {})
        model_stats[name] = {
            "pass_rate": s.get("pass_rate", 0),
            "total_e_count": s.get("total_e_count", 0),
            "failures": lang.get("failures"),
            "failure_rate": lang.get("failure_rate"),
        }
    return {
        "metadata": meta,
        "models": models,
        "default_model": best,
        "model_colors": default_model_colors(models),
        "model_stats": model_stats,
        "paragraphs": [by_para[k] for k in sorted(by_para.keys())],
    }


def main() -> None:
    if not FRENCH.is_file():
        print(f"Missing {FRENCH}")
        sys.exit(1)
    french_doc = json.loads(FRENCH.read_text(encoding="utf-8"))
    french_by_id = load_french_map()
    translations = load_all_translations()
    if not translations:
        print(f"No translation JSON files in {TRANS_DIR}")
        sys.exit(1)

    scores_models: list[dict] = []
    paragraph_scores: list[dict] = []

    para_ids = sorted(french_by_id.keys())
    for model_name, doc in sorted(translations.items()):
        rows = doc["paragraphs"]
        scored_rows = [r for r in rows if not r.get("exclude_from_score", False)]
        total_e = sum(r.get("e_count", 0) for r in scored_rows)
        e_free = sum(1 for r in scored_rows if r.get("e_count", 0) == 0)
        n = len(scored_rows)
        pass_rate = (e_free / n) if n else 0.0
        scores_models.append(
            {
                "name": model_name,
                "total_paragraphs": n,
                "e_free_paragraphs": e_free,
                "pass_rate": round(pass_rate, 4),
                "total_e_count": total_e,
                "first_failure_paragraph": first_failure(scored_rows),
            }
        )
    failures_by_model: dict[str, tuple[float, int]] = {}
    if LANG_SUMMARY.is_file():
        lang_doc = json.loads(LANG_SUMMARY.read_text(encoding="utf-8"))
        for row in lang_doc.get("models", []):
            if isinstance(row, dict) and row.get("model"):
                model = str(row["model"])
                failure_rate = float(row.get("failure_rate", 1.0))
                failures = int(row.get("failures", 10**9))
                failures_by_model[model] = (failure_rate, failures)
    # Rank with severe failure penalty first, then e-metrics and pass-rate.
    scores_models.sort(
        key=lambda s: (
            failures_by_model.get(s["name"], (1.0, 10**9))[0],
            failures_by_model.get(s["name"], (1.0, 10**9))[1],
            s["total_e_count"],
            -s["pass_rate"],
            s["name"],
        )
    )

    for pid in para_ids:
        cell = {"id": pid, "scores": {}}
        for model_name, doc in translations.items():
            row_by_id = {r["id"]: r for r in doc["paragraphs"]}
            r = row_by_id.get(pid)
            if not r:
                continue
            cell["scores"][model_name] = {"e_count": r.get("e_count", 0)}
        paragraph_scores.append(cell)

    out = {"models": scores_models, "paragraph_scores": paragraph_scores}
    SCORES_OUT.parent.mkdir(parents=True, exist_ok=True)
    SCORES_OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {SCORES_OUT}")

    site_doc = build_site_json(
        french_doc.get("metadata", {}),
        french_by_id,
        translations,
        scores_models,
    )
    SITE_DATA.parent.mkdir(parents=True, exist_ok=True)
    SITE_DATA.write_text(json.dumps(site_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {SITE_DATA}")


if __name__ == "__main__":
    main()
