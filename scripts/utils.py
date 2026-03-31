"""Shared helpers: Ollama HTTP API and Bedrock via AWS CLI (invoke-model)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_config(path: Path | None = None) -> dict[str, Any]:
    import yaml

    p = path or PROJECT_ROOT / "config.yaml"
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def count_e(text: str) -> tuple[int, list[int]]:
    positions = [i for i, c in enumerate(text) if c in ("e", "E")]
    return len(positions), positions


def _llama3_instruct_prompt(user_text: str) -> str:
    # Llama 3.x chat template (single turn)
    return (
        "<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n"
        f"{user_text}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
    )


def _mistral_instruct_prompt(user_text: str) -> str:
    return f"[INST] {user_text} [/INST]"


def _bedrock_request_body(model_id: str, prompt: str, temperature: float) -> dict[str, Any]:
    mid = model_id.lower()
    if "anthropic.claude" in mid:
        return {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 8192,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
    if "meta.llama" in mid or "meta.llama3" in mid:
        return {
            "prompt": _llama3_instruct_prompt(prompt),
            "max_gen_len": 8192,
            "temperature": temperature,
            "top_p": 0.9,
        }
    if "mistral." in mid:
        return {
            "prompt": _mistral_instruct_prompt(prompt),
            "max_tokens": 8192,
            "temperature": temperature,
            "top_p": 0.9,
        }
    if "amazon.nova" in mid:
        return {
            "messages": [
                {"role": "user", "content": [{"text": prompt}]},
            ],
            "inferenceConfig": {
                "maxTokens": 8192,
                "temperature": temperature,
            },
        }
    raise ValueError(f"Unsupported Bedrock model_id for CLI body builder: {model_id}")


def _extract_text_from_bedrock_response(model_id: str, resp: dict[str, Any]) -> str:
    mid = model_id.lower()
    if "anthropic.claude" in mid:
        blocks = resp.get("content") or []
        parts = []
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
        return "".join(parts).strip()
    if "meta.llama" in mid or "meta.llama3" in mid:
        return (resp.get("generation") or "").strip()
    if "mistral." in mid:
        outs = resp.get("outputs") or []
        if outs and isinstance(outs[0], dict):
            return (outs[0].get("text") or "").strip()
        return (resp.get("output_text") or "").strip()
    if "amazon.nova" in mid:
        out = resp.get("output") or {}
        msg = out.get("message") or {}
        content = msg.get("content") or []
        texts = []
        for c in content:
            if isinstance(c, dict) and "text" in c:
                texts.append(c["text"])
        return "".join(texts).strip()
    # Generic fallbacks
    for key in ("completion", "outputText", "text", "result"):
        if key in resp and isinstance(resp[key], str):
            return resp[key].strip()
    return json.dumps(resp)[:2000]


def bedrock_invoke_cli(region: str, model_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Call `aws bedrock-runtime invoke-model` and return parsed JSON response body."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as fin:
        json.dump(body, fin)
        in_path = fin.name
    out_path = in_path + ".out.json"
    try:
        cmd = [
            "aws",
            "bedrock-runtime",
            "invoke-model",
            "--region",
            region,
            "--model-id",
            model_id,
            "--body",
            f"file://{in_path}",
            "--cli-binary-format",
            "raw-in-base64-out",
            out_path,
        ]
        r = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            raise RuntimeError(
                f"aws bedrock-runtime invoke-model failed ({r.returncode}): {r.stderr or r.stdout}"
            )
        with open(out_path, encoding="utf-8") as f:
            return json.load(f)
    finally:
        try:
            os.unlink(in_path)
        except OSError:
            pass
        try:
            os.unlink(out_path)
        except OSError:
            pass


def translate_bedrock(
    region: str,
    model_id: str,
    prompt: str,
    temperature: float = 0.3,
) -> str:
    body = _bedrock_request_body(model_id, prompt, temperature)
    raw = bedrock_invoke_cli(region, model_id, body)
    return _extract_text_from_bedrock_response(model_id, raw)


def translate_ollama(
    base_url: str,
    model_id: str,
    prompt: str,
    temperature: float = 0.3,
    timeout_s: float = 120,
) -> str:
    import requests

    url = base_url.rstrip("/") + "/api/generate"
    payload = {
        "model": model_id,
        "prompt": prompt,
        "temperature": temperature,
        "stream": False,
    }
    r = requests.post(url, json=payload, timeout=timeout_s)
    r.raise_for_status()
    data = r.json()
    return (data.get("response") or "").strip()


def translate(
    provider: str,
    model_id: str,
    prompt: str,
    temperature: float = 0.3,
    *,
    ollama_base_url: str = "http://localhost:11434",
    bedrock_region: str = "us-east-1",
    ollama_timeout_s: float = 120,
) -> str:
    if provider == "ollama":
        return translate_ollama(ollama_base_url, model_id, prompt, temperature, ollama_timeout_s)
    if provider == "bedrock":
        return translate_bedrock(bedrock_region, model_id, prompt, temperature)
    if provider == "openai":
        raise ValueError(
            "OpenAI provider not wired in this scaffold; add openai package and API key or extend translate()."
        )
    raise ValueError(f"Unknown provider: {provider}")


def retry_with_backoff(fn, max_retries: int = 3, base_delay: float = 1.0):
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — pipeline resilience
            last_exc = e
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2**attempt)
            time.sleep(delay)
    raise last_exc  # pragma: no cover
