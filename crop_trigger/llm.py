"""Optional LLM layer. The system runs fully offline without it.

When an LLM is configured it is used for exactly two things, both behind guardrails:
  1. cross-checking the rule extraction (LLM reads the clause and returns JSON; any disagreement with the
     deterministic parser sends the case to a human);
  2. writing a short plain-language summary (numbers in the summary must all appear in the computed facts,
     otherwise the template summary is used instead).
It never does arithmetic and never decides the trigger.

Configure with environment variables:
  CTC_LLM=anthropic  ANTHROPIC_API_KEY=...  [CTC_MODEL=claude-sonnet-5-5]
  CTC_LLM=ollama     [OLLAMA_URL=http://localhost:11434] [CTC_MODEL=llama3.1]
Standard library only (urllib). NOTE: the Ollama client has been run against a live local Ollama; the
Anthropic client has not been run against the real API yet (see README).
"""
from __future__ import annotations

import json
import os
import urllib.request


class NullLLM:
    available = False
    name = "none"

    def complete(self, system: str, prompt: str) -> str:
        raise RuntimeError("no LLM configured")


class AnthropicLLM:
    available = True

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.model = model or os.environ.get("CTC_MODEL", "claude-sonnet-5-5")
        self.api_key = api_key or os.environ["ANTHROPIC_API_KEY"]
        self.name = f"anthropic:{self.model}"

    def complete(self, system: str, prompt: str) -> str:
        body = json.dumps({"model": self.model, "max_tokens": 800, "system": system,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
            "x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.load(r)
        return "".join(b.get("text", "") for b in data.get("content", []))


class OllamaLLM:
    available = True

    def __init__(self, model: str | None = None, url: str | None = None):
        self.model = model or os.environ.get("CTC_MODEL", "llama3.1")
        self.url = (url or os.environ.get("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
        self.name = f"ollama:{self.model}"

    def complete(self, system: str, prompt: str) -> str:
        body = json.dumps({"model": self.model, "stream": False, "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request(self.url + "/api/chat", data=body, headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)["message"]["content"]


def get_llm():
    kind = os.environ.get("CTC_LLM", "none").lower()
    try:
        if kind == "anthropic":
            return AnthropicLLM()
        if kind == "ollama":
            return OllamaLLM()
    except KeyError:
        pass
    return NullLLM()
