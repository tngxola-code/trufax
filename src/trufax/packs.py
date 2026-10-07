"""Domain packs: the shape of a domain's data, defined once and shared by every job.

A pack is a YAML file of entities. Each entity lists its fields (with types), its
key, its required fields and its rules. A job that names ``pack`` and ``entity``
only says where each field comes from; the pack supplies everything else, so two
jobs against different websites still produce identical columns and checks.

Built-in packs ship inside the package (``trufax/domain_packs``). Extra folders can be
added with the ``TRUFAX_PACKS`` environment variable (``os.pathsep``-separated).
"""

from __future__ import annotations

import os
from functools import cache
from importlib import resources
from pathlib import Path

import yaml
from pydantic import Field

from .config import FieldSpec, FieldType, JobConfig, Rule, Strict, ValidationConfig


class EntityField(Strict):
    type: FieldType = "string"
    description: str = ""
    personal_data: bool = False


class Entity(Strict):
    description: str = ""
    key: list[str] = Field(default_factory=list)
    required: list[str] = Field(default_factory=list)
    fields: dict[str, EntityField | FieldType]
    rules: list[Rule] = Field(default_factory=list)

    def field_specs(self) -> dict[str, EntityField]:
        return {
            n: f if isinstance(f, EntityField) else EntityField(type=f)
            for n, f in self.fields.items()
        }


class Pack(Strict):
    pack: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]*$")
    version: int = 1
    description: str = ""
    entities: dict[str, Entity]


class PackError(ValueError):
    pass


def _pack_dirs() -> list[Path]:
    dirs = [Path(str(resources.files("trufax").joinpath("domain_packs")))]
    extra = os.environ.get("TRUFAX_PACKS", "")
    dirs += [Path(p) for p in extra.split(os.pathsep) if p]
    return dirs


@cache
def _load_all(dirs: tuple[Path, ...]) -> dict[str, Pack]:
    packs: dict[str, Pack] = {}
    for d in dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.yaml")):
            pack = Pack.model_validate(yaml.safe_load(f.read_text(encoding="utf-8")))
            packs[pack.pack] = pack
    return packs


def available_packs() -> dict[str, Pack]:
    return _load_all(tuple(_pack_dirs()))


def get_pack(name: str) -> Pack:
    packs = available_packs()
    if name not in packs:
        raise PackError(f"unknown pack '{name}'; available: {sorted(packs)}")
    return packs[name]


def apply_pack(job: JobConfig) -> JobConfig:
    """Return a copy of the job with types, keys, required fields and rules from its
    pack's entity. Job-level settings win where both are given."""
    assert job.pack and job.entity
    pack = get_pack(job.pack)
    if job.entity not in pack.entities:
        raise PackError(
            f"pack '{pack.pack}' has no entity '{job.entity}'; available: {sorted(pack.entities)}"
        )
    entity = pack.entities[job.entity]
    efields = entity.field_specs()

    def typed(fields: dict[str, FieldSpec]) -> dict[str, FieldSpec | str]:
        out: dict[str, FieldSpec | str] = {}
        for name, spec in fields.items():
            if name not in efields:
                raise PackError(
                    f"field '{name}' is not part of {pack.pack}/{job.entity}; "
                    f"valid fields: {list(efields)}"
                )
            if spec.type is None:
                spec = spec.model_copy(update={"type": efields[name].type})
            out[name] = spec
        return out

    source = job.source.model_copy(update={"fields": typed(job.fields)})
    if source.html and source.html.detail:
        detail = source.html.detail.model_copy(update={"fields": typed(job.detail_fields)})
        source = source.model_copy(
            update={"html": source.html.model_copy(update={"detail": detail})}
        )

    v = job.validation
    validation = ValidationConfig(
        key=v.key or entity.key,
        required=list(dict.fromkeys(entity.required + v.required)),
        rules=entity.rules + v.rules,
        min_records=v.min_records,
    )
    return job.model_copy(
        update={"source": source, "validation": validation, "entity_fields": list(efields)}
    )
