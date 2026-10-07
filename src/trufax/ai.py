"""Local model extraction through Ollama, with a citation check.

A field with ``llm: "<what to find>"`` is filled by a local model reading the record's
text. The model is constrained to a JSON schema and told to copy values verbatim. Any
value that does not appear in the source text is rejected, so a model can find facts
but never invent them.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .config import AiSettings, FieldSpec

SYSTEM = (
    "You extract facts from the text you are given. For each requested field, copy the "
    "value exactly as it is written in the text, character for character. If the text "
    "does not contain a value for a field, return null for it. Never infer, translate, "
    "convert units or calculate."
)


class AiError(RuntimeError):
    pass


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace(" ", " ")).strip().casefold()


def cited(value: Any, context: str) -> bool:
    """True when the value appears verbatim (ignoring case and spacing) in the text."""
    v = _norm(str(value))
    return bool(v) and v in _norm(context)


class OllamaExtractor:
    def __init__(self, settings: AiSettings):
        self.s = settings
        self.calls = 0

    @property
    def label(self) -> str:
        return f"{self.s.provider}:{self.s.model}"

    def extract(self, context: str, specs: dict[str, FieldSpec]) -> dict[str, str | None]:
        schema = {
            "type": "object",
            "properties": {
                name: {"type": ["string", "null"], "description": spec.llm or name}
                for name, spec in specs.items()
            },
            "required": list(specs),
        }
        fields = "\n".join(f"- {name}: {spec.llm}" for name, spec in specs.items())
        text = context[: self.s.max_context_chars]
        body = {
            "model": self.s.model,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Fields:\n{fields}\n\nText:\n<<<\n{text}\n>>>"},
            ],
        }
        self.calls += 1
        try:
            resp = httpx.post(
                f"{self.s.base_url.rstrip('/')}/api/chat", json=body, timeout=self.s.timeout
            )
            resp.raise_for_status()
            content = resp.json()["message"]["content"]
            data = json.loads(content)
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise AiError(f"model call to {self.s.base_url} failed: {e}") from e
        if not isinstance(data, dict):
            raise AiError("model did not return a JSON object")
        return {n: (None if data.get(n) is None else str(data.get(n))) for n in specs}
