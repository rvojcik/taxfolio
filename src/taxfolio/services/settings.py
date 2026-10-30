"""User settings stored in the database: rate source per currency, default tax country, language.

Input sources (Flex Web Service, folders) have their own storage: ``services/sources.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from sqlalchemy import Engine, select
from sqlalchemy.dialects.sqlite import insert

from taxfolio.fx.converter import DEFAULT_SOURCES, TARGET_CURRENCIES, RateRule, RateSource
from taxfolio.i18n import LANGUAGES, N_
from taxfolio.storage import schema

TAX_COUNTRIES = {"CZ": N_("Česká republika"), "SK": N_("Slovenská republika")}  # translate on display
_RATES_KEY = "rate_rules"
_COUNTRY_KEY = "tax_country"
_LANGUAGE_KEY = "language"
_APPEARANCE_KEY = "appearance"
_CHECK_UPDATES_KEY = "check_updates"
APPEARANCES = ("", "light", "dark")  # "" = follow the operating system


@dataclass
class AppSettings:
    tax_country: str = "CZ"
    language: str = ""  # "" = follow the operating system
    appearance: str = ""  # "", "light" or "dark" (ui/theme.py)
    check_updates: bool = True  # look for a new release on GitHub once a day
    # (target currency, foreign currency) → rule; absent = default source of the target
    rate_rules: dict[tuple[str, str], RateRule] = field(default_factory=dict)

    def rule(self, target: str, currency: str) -> RateRule:
        return self.rate_rules.get((target, currency)) or RateRule(DEFAULT_SOURCES[target])


def load_settings(engine: Engine) -> AppSettings:
    t = schema.app_setting
    with engine.connect() as conn:
        raw = {key: value for key, value in conn.execute(select(t.c.key, t.c.value))}
    settings = AppSettings()
    if _COUNTRY_KEY in raw:
        country = json.loads(raw[_COUNTRY_KEY])
        if country in TAX_COUNTRIES:
            settings.tax_country = country
    language = json.loads(raw.get(_LANGUAGE_KEY, '""'))
    settings.language = language if language in LANGUAGES else ""
    appearance = json.loads(raw.get(_APPEARANCE_KEY, '""'))
    settings.appearance = appearance if appearance in APPEARANCES else ""
    settings.check_updates = bool(json.loads(raw.get(_CHECK_UPDATES_KEY, "true")))
    for item in json.loads(raw.get(_RATES_KEY, "[]")):
        try:
            target, ccy, source = item["target"], item["currency"], RateSource(item["source"])
            fixed = Decimal(item["fixed"]) if item.get("fixed") not in (None, "") else None
        except (KeyError, ValueError, InvalidOperation):
            continue  # ignore a malformed entry rather than refuse to start
        if target in TARGET_CURRENCIES:
            settings.rate_rules[(target, ccy)] = RateRule(source, fixed)
    return settings


def save_settings(engine: Engine, settings: AppSettings) -> None:
    rules = [
        {
            "target": target,
            "currency": ccy,
            "source": rule.source.value,
            "fixed": None if rule.fixed is None else str(rule.fixed),
        }
        for (target, ccy), rule in sorted(settings.rate_rules.items())
        # defaults are implicit; keep the stored list short
        if not (rule.source is DEFAULT_SOURCES[target] and rule.fixed is None)
    ]
    values = {
        _COUNTRY_KEY: json.dumps(settings.tax_country),
        _RATES_KEY: json.dumps(rules),
        _LANGUAGE_KEY: json.dumps(settings.language),
        _APPEARANCE_KEY: json.dumps(settings.appearance),
        _CHECK_UPDATES_KEY: json.dumps(settings.check_updates),
    }
    t = schema.app_setting
    with engine.begin() as conn:
        for key, value in values.items():
            stmt = insert(t).values(key=key, value=value)
            conn.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={"value": value}))
