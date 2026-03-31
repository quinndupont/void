#!/usr/bin/env python3
"""Translate each paragraph with each model; checkpoint per paragraph. Bedrock uses AWS CLI."""

import json
import re
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
    ollama_model_available,
    retry_with_backoff,
    translate,
)

FRENCH = PROJECT_ROOT / "data" / "french_clean.json"
PROMPT_FILE = PROJECT_ROOT / "prompts" / "translate.txt"
OUT_DIR = PROJECT_ROOT / "data" / "translations"
DEFAULT_PRE_TEXT_IDS = {"p0001", "p0156", "p0157"}
PRE_TEXT_TAGS = {"pre_text", "preface", "front_matter", "back_matter", "paratext"}
MAIN_START_TAGS = {"main_start", "start_main"}
MAIN_END_TAGS = {"main_end", "end_main"}


def load_prompt_template() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


def format_prompt(tpl: str, french_text: str) -> str:
    return tpl.replace("{french_text}", french_text)


def clean_translation_output(text: str) -> str:
    # Some models emit hidden reasoning wrapped in <think>...</think>.
    # Keep only the translated output content.
    cleaned = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.IGNORECASE | re.DOTALL)
    return cleaned.strip()


def estimate_tokens(text: str) -> int:
    # Lightweight tokenizer approximation for cross-provider consistency.
    return len(re.findall(r"\S+", text))


def load_french() -> list[dict]:
    data = json.loads(FRENCH.read_text(encoding="utf-8"))
    return data["paragraphs"]


def _as_tag_set(value) -> set[str]:
    if isinstance(value, str):
        return {value.strip().lower()} if value.strip() else set()
    if isinstance(value, list):
        tags: set[str] = set()
        for item in value:
            if isinstance(item, str) and item.strip():
                tags.add(item.strip().lower())
        return tags
    return set()


def paragraph_tags(para: dict) -> set[str]:
    tags: set[str] = set()
    for key in ("tags", "tag", "workflow_tags", "section", "section_tag", "text_type", "kind"):
        tags |= _as_tag_set(para.get(key))
    return tags


def resolve_translation_selection(cfg: dict, paragraphs: list[dict]) -> tuple[list[dict], dict]:
    tcfg = cfg.get("translate", {})
    mode_raw = str(tcfg.get("scope", "main_only")).strip().lower()
    mode = "all" if mode_raw == "all" else "main_only"
    pre_text_ids = {str(x) for x in (tcfg.get("pre_text_ids") or DEFAULT_PRE_TEXT_IDS)}

    start_idx = None
    end_idx = None
    tagged_pre_text_ids: set[str] = set()

    for idx, para in enumerate(paragraphs):
        pid = para["id"]
        tags = paragraph_tags(para)
        if tags & PRE_TEXT_TAGS:
            tagged_pre_text_ids.add(pid)
        if tags & MAIN_START_TAGS:
            if start_idx is not None:
                raise ValueError("Multiple main_start tags found in french_clean.json")
            start_idx = idx
        if tags & MAIN_END_TAGS:
            if end_idx is not None:
                raise ValueError("Multiple main_end tags found in french_clean.json")
            end_idx = idx

    if (start_idx is None) != (end_idx is None):
        raise ValueError("Both main_start and main_end tags are required when either is present")

    if start_idx is None and end_idx is None:
        is_pre_text = [p["id"] in pre_text_ids or p["id"] in tagged_pre_text_ids for p in paragraphs]
        main_indices = [i for i, pre in enumerate(is_pre_text) if not pre]
        if not main_indices:
            raise ValueError("No main text paragraphs found after pre-text exclusion")
        start_idx = main_indices[0]
        end_idx = main_indices[-1]

    if start_idx > end_idx:
        raise ValueError("main_start appears after main_end")

    main_slice = paragraphs[start_idx : end_idx + 1]
    main_ids = {p["id"] for p in main_slice}
    excluded_ids = [p["id"] for p in paragraphs if p["id"] not in main_ids]

    selected = paragraphs if mode == "all" else main_slice
    info = {
        "mode": mode,
        "main_start_id": paragraphs[start_idx]["id"],
        "main_end_id": paragraphs[end_idx]["id"],
        "excluded_pre_text_ids": excluded_ids,
        "total_paragraphs": len(paragraphs),
        "selected_paragraphs": len(selected),
    }
    return selected, info


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
            model_name=model_name,
            ollama_base_url=cfg.get("ollama", {}).get("base_url", "http://localhost:11434"),
            bedrock_region=cfg.get("bedrock", {}).get("region", "us-east-1"),
            ollama_timeout_s=float(cfg.get("translate", {}).get("ollama_timeout_s", 120)),
        )

    max_r = int(cfg.get("translate", {}).get("max_retries", 3))
    english = retry_with_backoff(run, max_retries=max_r)
    english = clean_translation_output(english)
    ms = int((time.perf_counter() - t0) * 1000)
    secs = ms / 1000 if ms > 0 else 0.0
    tok_out = estimate_tokens(english)
    tok_per_s = round(tok_out / secs, 3) if secs > 0 else 0.0
    n_e, pos = count_e(english)
    return {
        "id": pid,
        "french": text,
        "english": english,
        "token_count": tok_out,
        "tok_per_s": tok_per_s,
        "e_count": n_e,
        "e_positions": pos,
        "latency_ms": ms,
    }


def run_model(cfg: dict, model: dict, paragraphs: list[dict], tpl: str) -> None:
    name = model["name"]
    provider = model["provider"]
    mid = model["model_id"]
    temp = float(model.get("temperature", 0.3))
    if provider == "ollama":
        base_url = cfg.get("ollama", {}).get("base_url", "http://localhost:11434")
        ok, aliases = ollama_model_available(base_url, mid, name)
        if not ok:
            print(
                f"[{name}] SKIP model not found on {base_url}. "
                f"Tried aliases: {aliases}. Pull/load model first."
            )
            return
    path = translation_path(name)
    selected, selection_info = resolve_translation_selection(cfg, paragraphs)
    if selection_info["mode"] == "main_only":
        print(
            f"[{name}] mode=main_only span={selection_info['main_start_id']}..{selection_info['main_end_id']} "
            f"include={selection_info['selected_paragraphs']} exclude={len(selection_info['excluded_pre_text_ids'])}"
        )
    else:
        print(
            f"[{name}] mode=all span={selection_info['main_start_id']}..{selection_info['main_end_id']} "
            f"include={selection_info['selected_paragraphs']}"
        )

    existing = load_existing(path)
    test_cfg = cfg.get("translate_test") or {}
    test_enabled = bool(test_cfg.get("enabled", False))
    if existing is None:
        doc = {
            "model": name,
            "provider": provider,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "selection_mode": selection_info["mode"],
            "main_start_id": selection_info["main_start_id"],
            "main_end_id": selection_info["main_end_id"],
            "excluded_pre_text_ids": selection_info["excluded_pre_text_ids"],
            "paragraphs": [],
        }
        if test_enabled:
            doc["test_attempts"] = []
        done_ids: set[str] = set()
    else:
        doc = existing
        doc["selection_mode"] = selection_info["mode"]
        doc["main_start_id"] = selection_info["main_start_id"]
        doc["main_end_id"] = selection_info["main_end_id"]
        doc["excluded_pre_text_ids"] = selection_info["excluded_pre_text_ids"]
        if test_enabled and "test_attempts" not in doc:
            doc["test_attempts"] = []
        done_ids = {p["id"] for p in doc["paragraphs"]}

    pending = [p for p in selected if p["id"] not in done_ids]
    if not pending:
        print(f"[{name}] nothing to do ({len(selected)} already done)")
        return

    def is_missing_ollama_model(err: Exception) -> bool:
        msg = str(err).lower()
        return provider == "ollama" and "model" in msg and "not found" in msg

    def is_unavailable_bedrock_model(err: Exception) -> bool:
        msg = str(err).lower()
        return (
            provider == "bedrock"
            and "validationexception" in msg
            and (
                "inference profile" in msg
                or "on-demand throughput isn’t supported" in msg
                or "provided model identifier is invalid" in msg
                or "model identifier is invalid" in msg
            )
        )

    def is_ollama_timeout(err: Exception) -> bool:
        msg = str(err).lower()
        return provider == "ollama" and (
            "read timed out" in msg
            or "readtimeout" in msg
            or "timed out" in msg
        )

    if test_enabled:
        limit = int(test_cfg.get("limit", 3))
        if limit < 1:
            raise ValueError("translate_test.limit must be >= 1")
        tested_ids = {a.get("id") for a in doc.get("test_attempts", []) if isinstance(a, dict) and a.get("id")}
        if tested_ids:
            pending = [p for p in pending if p["id"] not in tested_ids]
        if not pending:
            print(f"[{name}] TEST MODE: nothing to do (all pending ids already tested)")
            return
        pending = pending[:limit]
        doc["test_mode"] = True
        doc["test_limit"] = limit
        save_translation(path, doc)
        print(f"[{name}] TEST MODE enabled; limiting to {len(pending)} paragraph(s)")

    def record_test_attempt(pid: str, status: str, error: str | None = None) -> None:
        if not test_enabled:
            return
        attempts = doc.setdefault("test_attempts", [])
        attempts.append(
            {
                "id": pid,
                "status": status,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": error,
            }
        )
        save_translation(path, doc)

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
                    if is_missing_ollama_model(e):
                        print(f"[{name}] SKIP missing local model during request: {e}")
                        record_test_attempt(p["id"], "skip_missing_model", str(e))
                        return
                    if is_ollama_timeout(e):
                        print(f"[{name}] TIMEOUT {p['id']}; skipping paragraph and continuing")
                        record_test_attempt(p["id"], "timeout", str(e))
                        continue
                    if is_unavailable_bedrock_model(e):
                        print(f"[{name}] SKIP unavailable Bedrock model configuration: {e}")
                        record_test_attempt(p["id"], "skip_unavailable_model", str(e))
                        return
                    print(f"[{name}] FAIL {p['id']}: {e}")
                    record_test_attempt(p["id"], "error", str(e))
                    raise
                with lock:
                    doc["paragraphs"].append(row)
                    doc["paragraphs"].sort(key=lambda x: x["id"])
                    record_test_attempt(row["id"], "ok")
                    save_translation(path, doc)
                print(
                    f"[{name}] {row['id']} e_count={row['e_count']} "
                    f"tok={row['token_count']} tok/s={row['tok_per_s']} {row['latency_ms']}ms"
                )
    else:
        for p in pending:
            try:
                row = translate_one(cfg, provider, mid, name, temp, tpl, p)
            except Exception as e:  # noqa: BLE001
                if is_missing_ollama_model(e):
                    print(f"[{name}] SKIP missing local model during request: {e}")
                    record_test_attempt(p["id"], "skip_missing_model", str(e))
                    return
                if is_ollama_timeout(e):
                    print(f"[{name}] TIMEOUT {p['id']}; skipping paragraph and continuing")
                    record_test_attempt(p["id"], "timeout", str(e))
                    continue
                if is_unavailable_bedrock_model(e):
                    print(f"[{name}] SKIP unavailable Bedrock model configuration: {e}")
                    record_test_attempt(p["id"], "skip_unavailable_model", str(e))
                    return
                print(f"[{name}] FAIL {p['id']}: {e}")
                record_test_attempt(p["id"], "error", str(e))
                raise
            doc["paragraphs"].append(row)
            doc["paragraphs"].sort(key=lambda x: x["id"])
            record_test_attempt(row["id"], "ok")
            save_translation(path, doc)
            print(
                f"[{name}] {row['id']} e_count={row['e_count']} "
                f"tok={row['token_count']} tok/s={row['tok_per_s']} {row['latency_ms']}ms"
            )


def parse_args(argv: list[str]) -> dict:
    args = {"test": False, "test_limit": 3}
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


def main() -> None:
    if not FRENCH.is_file():
        print(f"Missing {FRENCH}; run 03_cleanup.py first.")
        sys.exit(1)
    args = parse_args(sys.argv[1:])
    cfg = load_config()
    if args["test"]:
        cfg["translate_test"] = {"enabled": True, "limit": args["test_limit"]}
        print(f"TEST MODE: translating up to {args['test_limit']} pending paragraph(s) per model")
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
