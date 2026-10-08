import json
import os
import urllib.error
import urllib.request

BASE_URL = os.environ.get("VLLM_BASE_URL", "http://127.0.0.1:8500/v1")
MODEL = os.environ.get("VLLM_MODEL", "qwen-spec-poc")


def chat(messages, max_tokens=900):
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
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
    content = result["choices"][0]["message"].get("content")
    if not content:
        raise RuntimeError("vLLM returned an empty answer")
    return content.strip()
