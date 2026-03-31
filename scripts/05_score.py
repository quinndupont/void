#!/usr/bin/env python3
"""Aggregate e-metrics and optional judge scores; write data/scores.json and site/data.json."""

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from utils import (  # noqa: E402
    PROJECT_ROOT,
    load_config,
    retry_with_backoff,
    translate_bedrock,
)

FRENCH = PROJECT_ROOT / "data" / "french_clean.json"
TRANS_DIR = PROJECT_ROOT / "data" / "translations"
SCORES_OUT = PROJECT_ROOT / "data" / "scores.json"
SITE_DATA = PROJECT_ROOT / "site" / "data.json"
PROMPT_FLUENCY = PROJECT_ROOT / "prompts" / "judge.txt"


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


def run_judge(cfg: dict, kind: str, french: str, english: str) -> float | None:
    tpl_path = PROMPT_FLUENCY.parent / "judge.txt"
    if not tpl_path.is_file():
        return None
    region = cfg.get("bedrock", {}).get("region", "us-east-1")
    judge_id = cfg.get("judge", {}).get(
        "bedrock_model_id",
        "anthropic.claude-3-5-sonnet-20241022-v2:0",
    )
    if kind == "fluency":
        prompt = (
            "Rate the following English text for fluency and literary quality on a scale of 1-5. "
            "Consider natural rhythm, vocabulary richness, and readability. Output only the number.\n\n"
            f"---\n{english}"
        )
    elif kind == "fidelity":
        prompt = (
            "Rate how faithfully this English translation preserves the meaning of the French original, "
            "on a scale of 1-5. Ignore the absence of 'e' in your rating — focus only on semantic accuracy. "
            "Output only the number.\n\n"
            f"French:\n{french}\n\nEnglish:\n{english}"
        )
    else:
        return None

    def run():
        return translate_bedrock(region, judge_id, prompt, 0.1)

    try:
        text = retry_with_backoff(run, max_retries=2)
    except Exception:  # noqa: BLE001
        return None
    import re

    m = re.search(r"[1-5]", text)
    if not m:
        return None
    return float(m.group(0))


def build_site_json(
    meta: dict,
    french_by_id: dict,
    translations: dict[str, dict],
    scores_models: list[dict],
) -> dict:
    models = sorted(translations.keys())
    by_para: dict[str, dict] = {}
    for mid in models:
        doc = translations[mid]
        for row in doc["paragraphs"]:
            pid = row["id"]
            if pid not in by_para:
                fp = french_by_id[pid]
                by_para[pid] = {
                    "id": pid,
                    "chapter": fp.get("chapter", 1),
                    "french": fp["text"],
                    "translations": {},
                }
            by_para[pid]["translations"][mid] = {
                "text": row.get("english", ""),
                "e_count": row.get("e_count", 0),
            }
    pass_rates = {s["name"]: s.get("pass_rate", 0) for s in scores_models}
    best = max(models, key=lambda m: pass_rates.get(m, 0)) if models else None
    model_stats = {
        s["name"]: {
            "pass_rate": s.get("pass_rate", 0),
            "total_e_count": s.get("total_e_count", 0),
        }
        for s in scores_models
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
    cfg = load_config()
    if not FRENCH.is_file():
        print(f"Missing {FRENCH}")
        sys.exit(1)
    french_doc = json.loads(FRENCH.read_text(encoding="utf-8"))
    french_by_id = load_french_map()
    translations = load_all_translations()
    if not translations:
        print(f"No translation JSON files in {TRANS_DIR}")
        sys.exit(1)

    use_judge = "--judge" in sys.argv
    scores_models: list[dict] = []
    paragraph_scores: list[dict] = []

    para_ids = sorted(french_by_id.keys())
    for model_name, doc in sorted(translations.items()):
        rows = doc["paragraphs"]
        total_e = sum(r.get("e_count", 0) for r in rows)
        e_free = sum(1 for r in rows if r.get("e_count", 0) == 0)
        n = len(rows)
        pass_rate = (e_free / n) if n else 0.0
        entry = {
            "name": model_name,
            "total_paragraphs": n,
            "e_free_paragraphs": e_free,
            "pass_rate": round(pass_rate, 4),
            "total_e_count": total_e,
            "avg_fluency": None,
            "avg_fidelity": None,
            "first_failure_paragraph": first_failure(rows),
        }

        fluencies: list[float] = []
        fidelities: list[float] = []
        if use_judge and n > 0:
            # Judge first 20 paragraphs only by default to control cost
            cap = 20
            for r in sorted(rows, key=lambda x: x["id"])[:cap]:
                fr = r.get("french") or french_by_id[r["id"]]["text"]
                en = r.get("english", "")
                f1 = run_judge(cfg, "fluency", fr, en)
                f2 = run_judge(cfg, "fidelity", fr, en)
                if f1 is not None:
                    fluencies.append(f1)
                if f2 is not None:
                    fidelities.append(f2)
            if fluencies:
                entry["avg_fluency"] = round(sum(fluencies) / len(fluencies), 3)
            if fidelities:
                entry["avg_fidelity"] = round(sum(fidelities) / len(fidelities), 3)

        scores_models.append(entry)

    # Per-paragraph rollup
    for pid in para_ids:
        cell = {"id": pid, "scores": {}}
        for model_name, doc in translations.items():
            row_by_id = {r["id"]: r for r in doc["paragraphs"]}
            r = row_by_id.get(pid)
            if not r:
                continue
            cell["scores"][model_name] = {
                "e_count": r.get("e_count", 0),
                "fluency": None,
                "fidelity": None,
            }
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
    if not use_judge:
        print("Tip: run with --judge to call Bedrock for fluency/fidelity (costly).")


if __name__ == "__main__":
    main()
