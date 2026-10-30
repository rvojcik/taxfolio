"""Secrets of input sources (Flex Web Service tokens) in the OS keychain
(Keychain / Credential Manager / Secret Service).

Secrets never go into the database or a config file; each one is stored under
``source:<source id>:<field>``. ``IBKR_FLEX_TOKEN`` in the environment is used for IBKR sources
without a stored token – useful for the CLI on a headless machine without a keychain.
"""

from __future__ import annotations

import os

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from taxfolio.i18n import _

SERVICE = "taxfolio"
LEGACY_SERVICE = "ibkr-tax"  # keychain entries of versions before the rename to Taxfolio
LEGACY_USERNAME = "flex-web-service-token"  # the single token of versions before input sources
ENV_VAR = "IBKR_FLEX_TOKEN"


class SecretStoreError(RuntimeError):
    pass


def _username(source_id: str, key: str) -> str:
    return f"source:{source_id}:{key}"


def env_token() -> str | None:
    return os.environ.get(ENV_VAR) or None


def _get(username: str) -> str | None:
    try:
        value = keyring.get_password(SERVICE, username)
        if value is None and (value := keyring.get_password(LEGACY_SERVICE, username)) is not None:
            # stored under the old application name: move it over once
            keyring.set_password(SERVICE, username, value)
            try:
                keyring.delete_password(LEGACY_SERVICE, username)
            except PasswordDeleteError:
                pass
        return value
    except KeyringError as exc:
        raise SecretStoreError(
            _("Systémová klíčenka není dostupná: {error}. Použijte proměnnou {variable}.").format(
                error=exc, variable=ENV_VAR
            )
        ) from exc


def _delete(username: str) -> None:
    try:
        keyring.delete_password(SERVICE, username)
    except PasswordDeleteError:
        pass  # nothing stored
    except KeyringError as exc:
        raise SecretStoreError(_("Token nelze smazat: {error}").format(error=exc)) from exc


def get_secret(source_id: str, key: str) -> str | None:
    return _get(_username(source_id, key))


def set_secret(source_id: str, key: str, value: str) -> None:
    try:
        keyring.set_password(SERVICE, _username(source_id, key), value.strip())
    except KeyringError as exc:
        raise SecretStoreError(
            _("Token nelze uložit do systémové klíčenky: {error}").format(error=exc)
        ) from exc


def delete_secret(source_id: str, key: str) -> None:
    _delete(_username(source_id, key))


def get_legacy_token() -> str | None:
    return _get(LEGACY_USERNAME)


def delete_legacy_token() -> None:
    _delete(LEGACY_USERNAME)
