"""Shared adapter plumbing: turning raw values into a typed Record with provenance."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..ai import AiError, OllamaExtractor, cited
from ..config import FieldSpec, JobConfig
from ..fetch import Fetched, Fetcher
from ..records import Provenance, Record
from ..transforms import TransformError, clean
from ..validate import Check


class Adapter(ABC):
    def __init__(self, job: JobConfig, fetcher: Fetcher, limit: int | None = None):
        self.job = job
        self.fetcher = fetcher
        self.limit = limit
        self.checks: list[Check] = []
        self.warnings: list[str] = []
        self.ai = OllamaExtractor(job.ai) if job.uses_ai else None

    @abstractmethod
    def extract(self) -> list[Record]:
        """Fetch every source and return records (validation happens later)."""

    def full(self, records: list[Record]) -> bool:
        return self.limit is not None and len(records) >= self.limit

    def record(
        self,
        raw: dict[str, Any],
        specs: dict[str, FieldSpec],
        fetched: Fetched,
        locator: str,
        base_url: str = "",
        context: str | None = None,
    ) -> Record:
        return build_record(raw, specs, fetched, locator, base_url, context, self.ai)


def build_record(
    raw: dict[str, Any],
    specs: dict[str, FieldSpec],
    fetched: Fetched,
    locator: str,
    base_url: str = "",
    context: str | None = None,
    ai: OllamaExtractor | None = None,
) -> Record:
    data: dict[str, Any] = {}
    errors: list[str] = []
    ai_fields: list[str] = []

    fixed = {n: s.value for n, s in specs.items() if s.value is not None}
    if fixed:
        raw = {**raw, **fixed}
    llm_specs = {n: s for n, s in specs.items() if s.llm}
    if llm_specs:
        raw = dict(raw)
        if ai is None or not context:
            errors += [f"{n}: no text available for model extraction" for n in llm_specs]
        else:
            try:
                found = ai.extract(context, llm_specs)
            except AiError as e:
                found = {}
                errors += [f"{n}: {e}" for n in llm_specs]
            for name, value in found.items():
                raw[name] = value
                if value is None:
                    continue
                ai_fields.append(name)
                if not cited(value, context):
                    errors.append(f"{name}: model value {value!r} not found in the source text")

    for name, spec in specs.items():
        try:
            data[name] = clean(raw.get(name), spec, base_url or fetched.final_url)
        except TransformError as e:
            data[name] = raw.get(name)
            errors.append(f"{name}: {e}")
    prov = Provenance(
        source_url=fetched.final_url,
        source_sha256=fetched.sha256,
        fetched_at=fetched.fetched_at.isoformat(timespec="seconds"),
        locator=locator,
        ai_fields=f"{', '.join(ai_fields)} ({ai.label})" if ai_fields and ai else "",
    )
    return Record(data=data, provenance=prov, errors=errors)
