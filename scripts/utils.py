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
        # Newer Mistral models on Bedrock expect chat-style messages.
        if "mistral-large-3" in mid or "ministral-3" in mid or "magistral" in mid:
            return {
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 8192,
                "temperature": temperature,
                "top_p": 0.9,
            }
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
    model_name: str | None = None,
) -> str:
    import requests

    root = base_url.rstrip("/")

    # Primary Ollama-native endpoint.
    gen_url = root + "/api/generate"
    gen_payload = {
        "model": model_id,
        "prompt": prompt,
        "temperature": temperature,
        "stream": False,
    }
    r = requests.post(gen_url, json=gen_payload, timeout=timeout_s)
    if r.status_code < 400:
        data = r.json()
        return (data.get("response") or "").strip()

    # Fallback for OpenAI-compatible servers configured on the same base URL.
    if r.status_code == 404:
        chat_url = root + "/v1/chat/completions"
        candidate_models: list[str] = []
        for cand in (model_id, model_id.replace(":", "-"), model_id.split(":", 1)[0], model_name):
            if cand and cand not in candidate_models:
                candidate_models.append(cand)
        last_r = None
        for candidate in candidate_models:
            chat_payload = {
                "model": candidate,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "stream": False,
            }
            r2 = requests.post(chat_url, json=chat_payload, timeout=timeout_s)
            last_r = r2
            if r2.status_code < 400:
                data2 = r2.json()
                choices = data2.get("choices") or []
                if choices and isinstance(choices[0], dict):
                    msg = choices[0].get("message") or {}
                    return (msg.get("content") or "").strip()
                return ""
            # Keep trying aliases only for model-not-found 404s.
            if r2.status_code != 404:
                break
            body = (r2.text or "").lower()
            if "not found" not in body:
                break
        err2 = ((last_r.text if last_r is not None else "") or "").strip()
        raise requests.HTTPError(
            f"Ollama request failed ({last_r.status_code if last_r is not None else 404}) "
            f"at {chat_url} for model aliases {candidate_models}: {err2}",
            response=last_r,
        )

    err = (r.text or "").strip()
    raise requests.HTTPError(
        f"Ollama request failed ({r.status_code}) at {gen_url} for model '{model_id}': {err}",
        response=r,
    )


def translate(
    provider: str,
    model_id: str,
    prompt: str,
    temperature: float = 0.3,
    *,
    ollama_base_url: str = "http://localhost:11434",
    bedrock_region: str = "us-east-1",
    ollama_timeout_s: float = 120,
    model_name: str | None = None,
) -> str:
    if provider == "ollama":
        return translate_ollama(
            ollama_base_url,
            model_id,
            prompt,
            temperature,
            ollama_timeout_s,
            model_name=model_name,
        )
    if provider == "bedrock":
        return translate_bedrock(bedrock_region, model_id, prompt, temperature)
    if provider == "openai":
        raise ValueError(
            "OpenAI provider not wired in this scaffold; add openai package and API key or extend translate()."
        )
    raise ValueError(f"Unknown provider: {provider}")


def ollama_model_available(base_url: str, model_id: str, model_name: str | None = None) -> tuple[bool, list[str]]:
    """Check whether configured model aliases exist on local Ollama-compatible server."""
    import requests

    root = base_url.rstrip("/")
    aliases: list[str] = []
    for cand in (model_id, model_id.replace(":", "-"), model_id.split(":", 1)[0], model_name):
        if cand and cand not in aliases:
            aliases.append(cand)

    # Native Ollama model listing.
    try:
        r = requests.get(root + "/api/tags", timeout=10)
        if r.status_code < 400:
            data = r.json()
            names = {m.get("name", "") for m in (data.get("models") or []) if isinstance(m, dict)}
            names |= {n.split(":", 1)[0] for n in names}
            if any(a in names for a in aliases):
                return True, aliases
    except Exception:  # noqa: BLE001
        pass

    # OpenAI-compatible model listing.
    try:
        r2 = requests.get(root + "/v1/models", timeout=10)
        if r2.status_code < 400:
            data2 = r2.json()
            models = data2.get("data") or []
            ids = {m.get("id", "") for m in models if isinstance(m, dict)}
            ids |= {i.split(":", 1)[0] for i in ids}
            if any(a in ids for a in aliases):
                return True, aliases
    except Exception:  # noqa: BLE001
        pass

    return False, aliases


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
