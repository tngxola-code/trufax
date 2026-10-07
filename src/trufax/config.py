"""Job configuration: one YAML file describes one job end to end.

A job says where the data lives (source), how to read it (adapter settings and
fields), what "correct" means (validation and checks), and where it goes (output).
A job may also name a domain pack and entity; the pack then supplies field types,
keys, required fields and rules, so every job in a domain produces the same shape.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FieldType = Literal["string", "int", "decimal", "float", "date", "bool", "url"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldSpec(Strict):
    """Where a field comes from and how to clean it.

    ``src`` means a CSS/XPath selector for HTML, a column header or index for PDF
    tables, a regex group name for PDF text, and a relative path for XML. A list of
    paths (XML) is read in order and joined with ``join``. ``llm`` asks a local model
    to find the value in the record's text instead.
    """

    src: str | int | list[str] | None = None
    type: FieldType | None = None  # None: take it from the pack, else "string"
    transforms: list[str] = Field(default_factory=list)
    default: Any = None
    date_formats: list[str] = Field(default_factory=list)
    many: bool = False  # HTML: collect all matches joined by "; "
    join: str = "-"
    llm: str | None = Field(None, description="plain-language description for the model")
    value: Any = Field(None, description="a fixed value for every record, e.g. a currency")

    @property
    def extracted(self) -> bool:
        """False when the value comes from config or a model rather than a selector."""
        return not self.llm and self.value is None


class FetchSettings(Strict):
    engine: Literal["http", "browser"] = "http"
    rate_limit: float = Field(1.0, gt=0, description="max requests per second")
    timeout: float = 30.0
    retries: int = Field(3, ge=0)
    respect_robots: bool = True
    cache: bool = True
    user_agent: str = "trufax/0.2 (+data extraction; contact via client)"
    headers: dict[str, str] = Field(default_factory=dict)
    proxy: str | None = None
    wait_for: str | None = Field(None, description="browser engine: CSS selector to await")


class DetailSettings(Strict):
    link: str
    fields: dict[str, FieldSpec | str] = Field(default_factory=dict)


class HtmlSettings(Strict):
    item_selector: str | None = Field(
        None, description="one record per match; omit for one record per page"
    )
    next_page: str | None = None
    max_pages: int = Field(50, ge=1)
    detail: DetailSettings | None = None


class TotalCheck(Strict):
    """PDF: rows whose label matches are totals; data rows before them must sum to it."""

    label_field: str
    label_regex: str
    sum_fields: list[str]
    tolerance: float = 0.01


class PdfSettings(Strict):
    mode: Literal["table", "text"] = "table"
    pages: str | None = Field(None, description='e.g. "1-3,5"; default all')
    header_row: int = 0
    table_settings: dict[str, Any] = Field(default_factory=dict)
    row_regex: str | None = Field(None, description="text mode: regex with named groups")
    skip_rows_matching: list[str] = Field(default_factory=list)
    totals: list[TotalCheck] = Field(default_factory=list)


class XmlSettings(Strict):
    record_tag: str = Field(..., description="local tag name of one record element")


class SourceConfig(Strict):
    type: Literal["html", "pdf", "xml"]
    start_urls: list[str] = Field(default_factory=list)
    fetch: FetchSettings = Field(default_factory=FetchSettings)
    fields: dict[str, FieldSpec | str]
    html: HtmlSettings | None = None
    pdf: PdfSettings | None = None
    xml: XmlSettings | None = None

    @model_validator(mode="after")
    def _settings_for_type(self) -> SourceConfig:
        if not self.start_urls:
            raise ValueError("source.start_urls needs at least one URL or file path")
        if self.type == "html" and self.html is None:
            self.html = HtmlSettings()
        if self.type == "pdf" and self.pdf is None:
            self.pdf = PdfSettings()
        if self.type == "xml" and self.xml is None:
            raise ValueError("source.xml.record_tag is required for xml sources")
        if self.type == "pdf" and self.pdf and self.pdf.mode == "text" and not self.pdf.row_regex:
            raise ValueError("source.pdf.row_regex is required in text mode")
        return self


class Rule(Strict):
    field: str
    min: float | None = None
    max: float | None = None
    pattern: str | None = None
    one_of: list[Any] | None = None
    sum_of: list[str] | None = Field(None, description="field must equal the sum of these")
    tolerance: float = 0.01

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, v: str | None) -> str | None:
        if v is not None:
            re.compile(v)
        return v


class ValidationConfig(Strict):
    key: list[str] = Field(default_factory=list, description="fields that identify a record")
    required: list[str] = Field(default_factory=list)
    rules: list[Rule] = Field(default_factory=list)
    min_records: int = 0


class SheetsOutput(Strict):
    spreadsheet_id: str
    worksheet: str = "data"
    credentials_env: str = "GOOGLE_APPLICATION_CREDENTIALS"


OutputFormat = Literal["csv", "xlsx", "json"]


def _default_formats() -> list[OutputFormat]:
    return ["csv", "xlsx"]


class OutputConfig(Strict):
    dir: str = "output"
    formats: list[OutputFormat] = Field(default_factory=_default_formats)
    include_provenance: bool = True
    google_sheet: SheetsOutput | None = None


class AiSettings(Strict):
    """A local model served by Ollama. Only used by fields that set ``llm``."""

    provider: Literal["ollama"] = "ollama"
    base_url: str = Field(
        default_factory=lambda: os.environ.get("TRUFAX_OLLAMA_URL", "http://localhost:11434")
    )
    model: str = Field(default_factory=lambda: os.environ.get("TRUFAX_OLLAMA_MODEL", "qwen3:4b"))
    timeout: float = 120.0
    max_context_chars: int = 12000


class JobConfig(Strict):
    job: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]*$")
    description: str = ""
    client: str = ""
    pack: str | None = None
    entity: str | None = None
    source: SourceConfig
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    ai: AiSettings = Field(default_factory=AiSettings)
    entity_fields: list[str] = Field(default_factory=list, exclude=True)

    @model_validator(mode="after")
    def _pack_and_entity(self) -> JobConfig:
        if bool(self.pack) != bool(self.entity):
            raise ValueError("set both 'pack' and 'entity', or neither")
        return self

    @property
    def fields(self) -> dict[str, FieldSpec]:
        return normalise_fields(self.source.fields)

    @property
    def detail_fields(self) -> dict[str, FieldSpec]:
        html = self.source.html
        return normalise_fields(html.detail.fields) if html and html.detail else {}

    @property
    def output_fields(self) -> list[str]:
        """Every column a record can carry: the entity's fields when a pack is used,
        otherwise the job's own fields including ones read from detail pages."""
        if self.entity_fields:
            return list(self.entity_fields)
        names = list(self.fields)
        names += [n for n in self.detail_fields if n not in names]
        return names

    @property
    def uses_ai(self) -> bool:
        return any(s.llm for s in {**self.fields, **self.detail_fields}.values())


def normalise_fields(raw: dict[str, FieldSpec | str]) -> dict[str, FieldSpec]:
    return {k: v if isinstance(v, FieldSpec) else FieldSpec(src=v) for k, v in raw.items()}


class UnsafePath(ValueError):
    pass


def load_job(path: str | Path, local_root: Path | None = None) -> JobConfig:
    """Load a job file. Relative local paths in start_urls resolve against the file."""
    path = Path(path)
    return parse_job(path.read_text(encoding="utf-8"), path.parent, local_root, name=str(path))


def parse_job(
    text: str, base: Path, local_root: Path | None = None, name: str = "job"
) -> JobConfig:
    """Parse job YAML. With ``local_root`` set (the API does this), local file sources
    must sit inside that folder, so a job cannot read arbitrary files on the server."""
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"{name}: job file must be a YAML mapping")  # noqa: TRY004
    src = data.get("source") or {}
    urls = src.get("start_urls", []) if isinstance(src, dict) else []
    if isinstance(urls, list):
        src["start_urls"] = [_resolve(str(u), base, local_root) for u in urls]
    job = JobConfig.model_validate(data)
    if job.pack:
        from .packs import apply_pack  # local import: packs imports this module

        job = apply_pack(job)
    return job


def _resolve(u: str, base: Path, local_root: Path | None) -> str:
    if re.match(r"^[a-z][a-z0-9+.-]*://", u) and not u.startswith("file://"):
        return u
    p = Path(u.removeprefix("file://"))
    resolved = (p if p.is_absolute() else base / p).resolve()
    if local_root is not None:
        root = local_root.resolve()
        if root != resolved and root not in resolved.parents:
            raise UnsafePath(f"local source {u!r} is outside the allowed data folder")
    return str(resolved)
