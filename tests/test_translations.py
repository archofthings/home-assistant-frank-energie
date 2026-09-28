"""Tests that every new translation key exists (and is non-empty) in all locale files.

Covers the keys added by:
- commit 372b7c7 "Add get_prices action" (services.get_prices, exceptions.*)
- commit 366cea2 "Let users choose their delivery site and change it via
  reconfigure" (config.step.site, config.step.reconfigure, config.abort.*)
- commit d6a5dc3 "Add option for the time zone of price times"
  (options.step.init.*, selector.prices_timezone.options.*)

Without an entry in every locale file, Home Assistant falls back to showing
the raw key in the UI instead of human-readable text.
"""
import json
from pathlib import Path

import pytest

INTEGRATION_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "frank_energie"
LOCALE_FILES = [
    INTEGRATION_DIR / "strings.json",
    INTEGRATION_DIR / "translations" / "en.json",
    INTEGRATION_DIR / "translations" / "nl.json",
]


def _load(locale_file: Path) -> dict:
    return json.loads(locale_file.read_text(encoding="utf-8"))


def _get(data: dict, dotted_path: str):
    node = data
    for part in dotted_path.split("."):
        assert isinstance(node, dict), f"expected a dict while resolving {dotted_path!r} at {part!r}"
        assert part in node, f"missing key {dotted_path!r} (no {part!r})"
        node = node[part]
    return node


NEW_KEYS = [
    # get_prices service (372b7c7)
    "services.get_prices.name",
    "services.get_prices.description",
    "services.get_prices.fields.config_entry_id.name",
    "services.get_prices.fields.config_entry_id.description",
    "services.get_prices.fields.start.name",
    "services.get_prices.fields.start.description",
    "services.get_prices.fields.end.name",
    "services.get_prices.fields.end.description",
    # get_prices service exceptions (372b7c7)
    "exceptions.entry_not_found.message",
    "exceptions.entry_not_loaded.message",
    "exceptions.invalid_period.message",
    # site selection / reconfigure (366cea2)
    "config.step.site.title",
    "config.step.site.data.site_reference",
    "config.step.reconfigure.title",
    "config.step.reconfigure.data.site_reference",
    "config.abort.no_sites",
    "config.abort.reconfigure_successful",
    "config.abort.reconfigure_not_supported",
    # prices_timezone option (d6a5dc3)
    "options.step.init.title",
    "options.step.init.description",
    "options.step.init.data.prices_timezone",
    "selector.prices_timezone.options.home_assistant",
    "selector.prices_timezone.options.utc",
    # strings.json/en.json/nl.json drift fix: keys that were present in
    # en.json/nl.json but missing from strings.json (see the "Tidy time zone
    # lookup, action validation and translations" review round).
    "config.step.login.title",
    "config.step.login.data.username",
    "config.step.login.data.password",
    "config.step.user.title",
    "config.step.user.data.authentication",
    "config.error.invalid_auth",
    "config.abort.already_configured",
    "config.abort.reauth_successful",
    "title",
]


@pytest.mark.parametrize("locale_file", LOCALE_FILES, ids=lambda p: p.name)
@pytest.mark.parametrize("dotted_path", NEW_KEYS)
def test_new_translation_key_exists_and_is_non_empty(locale_file, dotted_path):
    """Every new key must exist and hold a non-empty string in every locale file."""
    data = _load(locale_file)
    value = _get(data, dotted_path)

    assert isinstance(value, str)
    assert value.strip() != ""


def test_exception_messages_use_the_entry_id_placeholder():
    """entry_not_found/entry_not_loaded messages must reference {entry_id} in every locale file."""
    for locale_file in LOCALE_FILES:
        data = _load(locale_file)
        for key in ("entry_not_found", "entry_not_loaded"):
            message = _get(data, f"exceptions.{key}.message")
            assert "{entry_id}" in message, f"{locale_file.name}: exceptions.{key}.message missing {{entry_id}}"


# --------------------------------------------------------------------------
# single_instance_allowed: present in strings.json (source template) and now
# in nl.json; intentionally not added to en.json in this round (see spec).
# --------------------------------------------------------------------------

SINGLE_INSTANCE_ALLOWED_LOCALE_FILES = [
    INTEGRATION_DIR / "strings.json",
    INTEGRATION_DIR / "translations" / "nl.json",
]


@pytest.mark.parametrize("locale_file", SINGLE_INSTANCE_ALLOWED_LOCALE_FILES, ids=lambda p: p.name)
def test_single_instance_allowed_exists_and_is_non_empty(locale_file):
    """config.abort.single_instance_allowed must exist and be non-empty in strings.json and nl.json."""
    data = _load(locale_file)
    value = _get(data, "config.abort.single_instance_allowed")

    assert isinstance(value, str)
    assert value.strip() != ""
