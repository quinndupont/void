#!/usr/bin/env python3
"""Translate each paragraph with each model; checkpoint per paragraph. Bedrock uses AWS CLI."""

import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from utils import (  # noqa: E402
    PROJECT_ROOT,
    count_e,
    load_config,
    retry_with_backoff,
    translate,
)

FRENCH = PROJECT_ROOT / "data" / "french_clean.json"
PROMPT_FILE = PROJECT_ROOT / "prompts" / "translate.txt"
OUT_DIR = PROJECT_ROOT / "data" / "translations"


def load_prompt_template() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


def format_prompt(tpl: str, french_text: str) -> str:
    return tpl.replace("{french_text}", french_text)


def load_french() -> list[dict]:
    data = json.loads(FRENCH.read_text(encoding="utf-8"))
    return data["paragraphs"]


def translation_path(model_name: str) -> Path:
    safe = model_name.replace("/", "-")
    return OUT_DIR / f"{safe}.json"


def load_existing(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_translation(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def translate_one(
    cfg: dict,
    provider: str,
    model_id: str,
    model_name: str,
    temperature: float,
    tpl: str,
    para: dict,
) -> dict:
    pid = para["id"]
    text = para["text"]
    prompt = format_prompt(tpl, text)
    t0 = time.perf_counter()

    def run():
        return translate(
            provider,
            model_id,
            prompt,
            temperature,
            ollama_base_url=cfg.get("ollama", {}).get("base_url", "http://localhost:11434"),
            bedrock_region=cfg.get("bedrock", {}).get("region", "us-east-1"),
            ollama_timeout_s=float(cfg.get("translate", {}).get("ollama_timeout_s", 120)),
        )

    max_r = int(cfg.get("translate", {}).get("max_retries", 3))
    english = retry_with_backoff(run, max_retries=max_r)
    ms = int((time.perf_counter() - t0) * 1000)
    n_e, pos = count_e(english)
    return {
        "id": pid,
        "french": text,
        "english": english,
        "e_count": n_e,
        "e_positions": pos,
        "latency_ms": ms,
    }


def run_model(cfg: dict, model: dict, paragraphs: list[dict], tpl: str) -> None:
    name = model["name"]
    provider = model["provider"]
    mid = model["model_id"]
    temp = float(model.get("temperature", 0.3))
    path = translation_path(name)
    existing = load_existing(path)
    if existing is None:
        doc = {
            "model": name,
            "provider": provider,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "paragraphs": [],
        }
        done_ids: set[str] = set()
    else:
        doc = existing
        done_ids = {p["id"] for p in doc["paragraphs"]}

    pending = [p for p in paragraphs if p["id"] not in done_ids]
    if not pending:
        print(f"[{name}] nothing to do ({len(paragraphs)} already done)")
        return

    conc = int(cfg.get("translate", {}).get("bedrock_concurrency", 2))
    print(f"[{name}] translating {len(pending)} paragraphs (provider={provider})…")

    if provider == "bedrock" and conc > 1:
        lock = threading.Lock()

        def work(p):
            return translate_one(cfg, provider, mid, name, temp, tpl, p)

        with ThreadPoolExecutor(max_workers=conc) as ex:
            futs = {ex.submit(work, p): p for p in pending}
            for fut in as_completed(futs):
                p = futs[fut]
                try:
                    row = fut.result()
                except Exception as e:  # noqa: BLE001
                    print(f"[{name}] FAIL {p['id']}: {e}")
                    raise
                with lock:
                    doc["paragraphs"].append(row)
                    doc["paragraphs"].sort(key=lambda x: x["id"])
                    save_translation(path, doc)
                print(f"[{name}] {row['id']} e_count={row['e_count']} {row['latency_ms']}ms")
    else:
        for p in pending:
            try:
                row = translate_one(cfg, provider, mid, name, temp, tpl, p)
            except Exception as e:  # noqa: BLE001
                print(f"[{name}] FAIL {p['id']}: {e}")
                raise
            doc["paragraphs"].append(row)
            doc["paragraphs"].sort(key=lambda x: x["id"])
            save_translation(path, doc)
            print(f"[{name}] {row['id']} e_count={row['e_count']} {row['latency_ms']}ms")


def main() -> None:
    if not FRENCH.is_file():
        print(f"Missing {FRENCH}; run 03_cleanup.py first.")
        sys.exit(1)
    cfg = load_config()
    paragraphs = load_french()
    tpl = load_prompt_template()
    models = cfg.get("models") or []
    if not models:
        print("No models in config.yaml")
        sys.exit(1)
    for m in models:
        run_model(cfg, m, paragraphs, tpl)
    print("Done.")


if __name__ == "__main__":
    main()
