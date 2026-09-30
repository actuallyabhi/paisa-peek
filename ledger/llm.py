"""Minimal client for any OpenAI-compatible chat endpoint (Ollama by default). Off unless LLM_MODEL is set."""

import json
import urllib.request

from django.conf import settings


class LLMError(Exception):
    pass


def enabled() -> bool:
    return bool(settings.LLM_MODEL)


def chat_json(system: str, user: str, schema: dict) -> dict:
    """One chat call constrained to a JSON schema; returns the parsed object."""
    body = {
        "model": settings.LLM_MODEL,
        "temperature": 0,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "result", "schema": schema, "strict": True}},
    }
    req = urllib.request.Request(
        settings.LLM_BASE_URL.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {settings.LLM_API_KEY or 'none'}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=settings.LLM_TIMEOUT) as resp:
            content = json.load(resp)["choices"][0]["message"]["content"]
        return json.loads(content)
    except (OSError, KeyError, IndexError, ValueError) as e:
        raise LLMError(str(e)) from e
