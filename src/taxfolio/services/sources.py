"""Input sources: saved configurations the data is updated from with one click.

A source has a type (IBKR Flex Web Service, a folder with exports, …), a name and its settings.
Settings are stored in the database (``app_setting`` → ``input_sources``); fields marked secret
(tokens) go only to the OS keychain under the source's id, never into the database.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy import Engine, select
from sqlalchemy.dialects.sqlite import insert

from taxfolio.i18n import N_
from taxfolio.services import secrets
from taxfolio.storage import schema

_SOURCES_KEY = "input_sources"
_LEGACY_FLEX_QUERY_KEY = "flex_query_id"  # before input sources: one Flex Query in the settings


class SourceType(StrEnum):
    IBKR_FLEX = "ibkr_flex"
    FOLDER = "folder"


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str  # Czech source text, translate with _() on display
    secret: bool = False
    required: bool = True
    placeholder: str = ""
    folder: bool = False  # offer a folder picker
    default: str = ""


@dataclass(frozen=True)
class SourceTypeSpec:
    title: str
    description: str
    fields: tuple[FieldSpec, ...]
    uses_period: bool  # downloads a chosen period (otherwise takes whatever is new)


SOURCE_TYPES: dict[SourceType, SourceTypeSpec] = {
    SourceType.IBKR_FLEX: SourceTypeSpec(
        N_("IBKR – Flex Web Service"),
        N_(
            "Stahuje výpis Flex Query přímo z Interactive Brokers. Query ID je číslo dotazu "
            "taxfolio_full (Client Portal → Performance & Reports → Flex Queries), token vygenerujete "
            "v Settings → Flex Web Service."
        ),
        (
            FieldSpec("query_id", N_("Query ID"), placeholder=N_("číslo Flex Query, např. 123456")),
            FieldSpec("token", N_("Token"), secret=True, placeholder=N_("uloží se do systémové klíčenky")),
        ),
        uses_period=True,
    ),
    SourceType.FOLDER: SourceTypeSpec(
        N_("Složka s exporty (IBKR, XTB)"),
        N_(
            "Importuje nové soubory ze složky – např. exporty z XTB nebo výpisy z IBKR, které stahujete "
            "ručně. Soubory, které už byly importovány, se přeskočí."
        ),
        (
            FieldSpec("path", N_("Složka"), folder=True, placeholder=N_("např. ~/Stažené/XTB")),
            FieldSpec(
                "pattern",
                N_("Soubory"),
                required=False,
                placeholder="*.csv *.xml *.xlsx",
                default="*.csv *.xml *.xlsx",
            ),
        ),
        uses_period=False,
    ),
}


@dataclass
class InputSource:
    type: SourceType
    name: str
    settings: dict[str, str] = field(default_factory=dict)  # non-secret fields only
    enabled: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def spec(self) -> SourceTypeSpec:
        return SOURCE_TYPES[self.type]

    def value(self, key: str) -> str:
        spec = next(f for f in self.spec.fields if f.key == key)
        return self.settings.get(key, "").strip() or spec.default

    def secret(self, key: str) -> str | None:
        if self.type is SourceType.IBKR_FLEX and key == "token":
            return secrets.get_secret(self.id, key) or secrets.env_token()
        return secrets.get_secret(self.id, key)

    def missing(self) -> list[FieldSpec]:
        """Required fields without a value (a secret counts when it is in the keychain)."""
        out = []
        for f in self.spec.fields:
            if not f.required:
                continue
            present = self.secret(f.key) if f.secret else self.value(f.key)
            if not present:
                out.append(f)
        return out


def load_sources(engine: Engine) -> list[InputSource]:
    t = schema.app_setting
    with engine.connect() as conn:
        raw = {k: v for k, v in conn.execute(select(t.c.key, t.c.value))}
    if _SOURCES_KEY not in raw:
        return _migrate_legacy(engine, raw)
    out = []
    for item in json.loads(raw[_SOURCES_KEY]):
        try:
            out.append(
                InputSource(
                    type=SourceType(item["type"]),
                    name=str(item["name"]),
                    settings={str(k): str(v) for k, v in item.get("settings", {}).items()},
                    enabled=bool(item.get("enabled", True)),
                    id=str(item["id"]),
                )
            )
        except (KeyError, ValueError):
            continue  # an unknown type from a newer version: skip rather than refuse to start
    return out


def save_sources(engine: Engine, sources: list[InputSource]) -> None:
    payload = json.dumps(
        [
            {
                "id": s.id,
                "type": s.type.value,
                "name": s.name,
                "enabled": s.enabled,
                # secrets never reach the database, even if a caller put one in the settings
                "settings": {k: v for k, v in s.settings.items() if not _is_secret(s.type, k)},
            }
            for s in sources
        ],
        ensure_ascii=False,
    )
    t = schema.app_setting
    with engine.begin() as conn:
        stmt = insert(t).values(key=_SOURCES_KEY, value=payload)
        conn.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={"value": payload}))


def remove_source(engine: Engine, source_id: str) -> None:
    sources = load_sources(engine)
    for s in sources:
        if s.id == source_id:
            for f in s.spec.fields:
                if f.secret:
                    secrets.delete_secret(s.id, f.key)
    save_sources(engine, [s for s in sources if s.id != source_id])


def _is_secret(kind: SourceType, key: str) -> bool:
    return any(f.secret and f.key == key for f in SOURCE_TYPES[kind].fields)


def _migrate_legacy(engine: Engine, raw: dict[str, str]) -> list[InputSource]:
    """Turn the single Flex Query of older versions into the first input source."""
    sources: list[InputSource] = []
    query_id = str(json.loads(raw.get(_LEGACY_FLEX_QUERY_KEY, '""'))).strip()
    if query_id:
        source = InputSource(SourceType.IBKR_FLEX, "IBKR", {"query_id": query_id})
        try:
            token = secrets.get_legacy_token()
        except secrets.SecretStoreError:
            token = None
        if token:
            secrets.set_secret(source.id, "token", token)
            secrets.delete_legacy_token()
        sources.append(source)
    save_sources(engine, sources)
    return sources
