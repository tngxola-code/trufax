"""A record is the cleaned data plus where it came from."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

VALID, INVALID, DUPLICATE = "VALID", "INVALID", "DUPLICATE"

PROVENANCE_COLUMNS = ["_source_url", "_locator", "_source_sha256", "_fetched_at", "_ai_fields"]


@dataclass
class Provenance:
    source_url: str
    source_sha256: str
    fetched_at: str
    locator: str  # where in the source: "item 3", "page 2 row 7", "record 15"
    ai_fields: str = ""  # fields a local model filled, and which model


@dataclass
class Record:
    data: dict[str, Any]
    provenance: Provenance
    status: str = VALID
    errors: list[str] = field(default_factory=list)

    def flat(self, include_provenance: bool = True) -> dict[str, Any]:
        row = dict(self.data)
        if include_provenance:
            row["_source_url"] = self.provenance.source_url
            row["_locator"] = self.provenance.locator
            row["_source_sha256"] = self.provenance.source_sha256
            row["_fetched_at"] = self.provenance.fetched_at
            row["_ai_fields"] = self.provenance.ai_fields
        return row
