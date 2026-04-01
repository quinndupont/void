#!/usr/bin/env python3
"""Translate page-1 split text: pre-text (normal) + main-text (lipogram)."""

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from utils import (  # noqa: E402
    PROJECT_ROOT,
    count_e,
    load_config,
    ollama_model_available,
    retry_with_backoff,
    translate,
)

FRENCH = PROJECT_ROOT / "data" / "french_clean.json"
PROMPT_MAIN_FILE = PROJECT_ROOT / "prompts" / "translate.txt"
PROMPT_PRE_FILE = PROJECT_ROOT / "prompts" / "translate_pretext.txt"
OUT_DIR = PROJECT_ROOT / "data" / "translations"
MARKER = "---MAIN_TEXT---"
PAGE1_ID = "p0001"
PRE_ID = "p0001_pre"
MAIN_ID = "p0001_main"


def load_prompt_template(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def format_prompt(tpl: str, french_text: str) -> str:
    return tpl.replace("{french_text}", french_text)


def clean_translation_output(text: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.IGNORECASE | re.DOTALL)
    return cleaned.strip()


def estimate_tokens(text: str) -> int:
    return len(re.findall(r"\S+", text))


def load_page1_parts() -> tuple[str, str]:
    data = json.loads(FRENCH.read_text(encoding="utf-8"))
    para = next((p for p in data.get("paragraphs", []) if p.get("id") == PAGE1_ID), None)
    if para is None:
        raise ValueError(f"Could not find {PAGE1_ID} in {FRENCH}")
    text = para.get("text", "")
    if MARKER not in text:
        raise ValueError(f"Missing marker {MARKER!r} in {PAGE1_ID} text")
    pre, main = text.split(MARKER, 1)
    pre = pre.strip()
    main = main.strip()
    if not pre or not main:
        raise ValueError(f"Split around {MARKER!r} produced an empty section")
    return pre, main


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


def translate_row(
    cfg: dict,
    provider: str,
    model_id: str,
    model_name: str,
    temperature: float,
    prompt_tpl: str,
    pid: str,
    french_text: str,
    *,
    exclude_from_score: bool = False,
) -> dict:
    prompt = format_prompt(prompt_tpl, french_text)
    t0 = time.perf_counter()

    def run():
        return translate(
            provider,
            model_id,
            prompt,
            temperature,
            model_name=model_name,
            ollama_base_url=cfg.get("ollama", {}).get("base_url", "http://localhost:11434"),
            bedrock_region=cfg.get("bedrock", {}).get("region", "us-east-1"),
            ollama_timeout_s=float(cfg.get("translate", {}).get("ollama_timeout_s", 120)),
            gemini_timeout_s=float(cfg.get("translate", {}).get("gemini_timeout_s", 120)),
        )

    max_r = int(cfg.get("translate", {}).get("max_retries", 3))
    english = retry_with_backoff(run, max_retries=max_r)
    english = clean_translation_output(english)
    if not english.strip():
        raise RuntimeError(f"Empty translation output for {model_name} on {pid}")

    ms = int((time.perf_counter() - t0) * 1000)
    secs = ms / 1000 if ms > 0 else 0.0
    tok_out = estimate_tokens(english)
    tok_per_s = round(tok_out / secs, 3) if secs > 0 else 0.0
    n_e, pos = count_e(english)
    row = {
        "id": pid,
        "french": french_text,
        "english": english,
        "token_count": tok_out,
        "tok_per_s": tok_per_s,
        "e_count": n_e,
        "e_positions": pos,
        "latency_ms": ms,
    }
    if exclude_from_score:
        row["exclude_from_score"] = True
    return row


def parse_args(argv: list[str]) -> dict:
    args = {"test": False, "test_limit": 1}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--test":
            args["test"] = True
            i += 1
            continue
        if a == "--test-limit":
            if i + 1 >= len(argv):
                raise SystemExit("--test-limit requires a value")
            try:
                args["test_limit"] = int(argv[i + 1])
            except ValueError as e:
                raise SystemExit("--test-limit must be an integer") from e
            i += 2
            continue
        raise SystemExit(f"Unknown argument: {a}")
    if args["test_limit"] < 1:
        raise SystemExit("--test-limit must be >= 1")
    return args


def run_model(
    cfg: dict,
    model: dict,
    pre_text: str,
    main_text: str,
    pre_prompt: str,
    main_prompt: str,
    *,
    test_enabled: bool,
    test_limit: int,
) -> None:
    name = model["name"]
    provider = model["provider"]
    model_id = model["model_id"]
    temp = float(model.get("temperature", 0.3))

    if provider == "ollama":
        base_url = cfg.get("ollama", {}).get("base_url", "http://localhost:11434")
        ok, aliases = ollama_model_available(base_url, model_id, name)
        if not ok:
            print(
                f"[{name}] SKIP model not found on {base_url}. "
                f"Tried aliases: {aliases}. Pull/load model first."
            )
            return

    path = translation_path(name)
    existing = load_existing(path)
    if existing is None:
        doc = {
            "model": name,
            "provider": provider,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "paragraphs": [],
        }
    else:
        doc = existing

    rows = [r for r in doc.get("paragraphs", []) if isinstance(r, dict)]
    by_id = {r.get("id"): r for r in rows if r.get("id")}

    pending_defs = []
    if PRE_ID not in by_id:
        pending_defs.append((PRE_ID, pre_text, pre_prompt, True))
    if MAIN_ID not in by_id:
        pending_defs.append((MAIN_ID, main_text, main_prompt, False))

    if not pending_defs:
        print(f"[{name}] nothing to do ({PRE_ID} and {MAIN_ID} already exist)")
        return

    if test_enabled:
        pending_defs = pending_defs[:test_limit]
        print(f"[{name}] TEST MODE enabled; limiting to {len(pending_defs)} segment(s)")

    for pid, french_text, prompt_tpl, exclude in pending_defs:
        row = translate_row(
            cfg,
            provider,
            model_id,
            name,
            temp,
            prompt_tpl,
            pid,
            french_text,
            exclude_from_score=exclude,
        )
        rows = [r for r in rows if r.get("id") != pid]
        rows.append(row)
        rows.sort(key=lambda x: x["id"])
        doc["paragraphs"] = rows
        save_translation(path, doc)
        print(
            f"[{name}] {pid} e_count={row['e_count']} tok={row['token_count']} "
            f"tok/s={row['tok_per_s']} {row['latency_ms']}ms"
        )


def main() -> None:
    if not FRENCH.is_file():
        print(f"Missing {FRENCH}; run 03_cleanup.py first.")
        sys.exit(1)
    if not PROMPT_MAIN_FILE.is_file() or not PROMPT_PRE_FILE.is_file():
        print("Missing prompt template(s); expected translate.txt and translate_pretext.txt")
        sys.exit(1)

    args = parse_args(sys.argv[1:])
    cfg = load_config()
    pre_text, main_text = load_page1_parts()
    pre_prompt = load_prompt_template(PROMPT_PRE_FILE)
    main_prompt = load_prompt_template(PROMPT_MAIN_FILE)

    models = cfg.get("models") or []
    if not models:
        print("No models in config.yaml")
        sys.exit(1)

    if args["test"]:
        print(f"TEST MODE: translating up to {args['test_limit']} pending segment(s) per model")
    for m in models:
        run_model(
            cfg,
            m,
            pre_text,
            main_text,
            pre_prompt,
            main_prompt,
            test_enabled=args["test"],
            test_limit=args["test_limit"],
        )
    print("Done.")


if __name__ == "__main__":
    main()
