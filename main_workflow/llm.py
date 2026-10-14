import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
if ENV_FILE.exists():
    # VLLM_* settings from the repository's .env; the environment still wins
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip().startswith("VLLM_"):
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))

BASE_URL = os.environ.get("VLLM_BASE_URL", "http://127.0.0.1:8500/v1")
MODEL = os.environ.get("VLLM_MODEL", "qwen-spec-poc")


def chat(messages, max_tokens=900):
    content = complete(messages, max_tokens).get("content")
    if not content:
        raise RuntimeError("vLLM returned an empty answer")
    return content.strip()


def complete(messages, max_tokens=900, tools=None):
    """One chat completion. Returns the reply message: its content, and its tool_calls when tools are offered."""
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
        **({"tools": tools} if tools else {}),
    }
    request = urllib.request.Request(
        BASE_URL.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(500).decode("utf-8", errors="replace")
        raise RuntimeError(f"vLLM returned HTTP {exc.code}: {detail}") from exc
    return result["choices"][0]["message"]
