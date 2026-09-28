"""Tests that strings.json, en.json and nl.json stay in sync and usable.

Without a matching, non-empty entry in every locale file, Home Assistant
falls back to showing the raw key in the UI instead of human-readable text.
"""
import json
from pathlib import Path

import pytest

INTEGRATION_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "frank_energie"
LOCALE_FILES = {
    "strings.json": INTEGRATION_DIR / "strings.json",
    "en.json": INTEGRATION_DIR / "translations" / "en.json",
    "nl.json": INTEGRATION_DIR / "translations" / "nl.json",
}

# Keys that are intentionally absent from a given locale file.
KNOWN_EXCEPTIONS = {
    # single_instance_allowed is present in strings.json (source template) and
    # nl.json, but intentionally not translated into en.json.
    "en.json": {"config.abort.single_instance_allowed"},
}

# A short list of keys that must exist (with real text) in every locale file:
# the get_prices service and its exceptions, the site/reconfigure config flow
# steps, the abort reasons and the prices_timezone option/selector. Some
# entries additionally require a specific substring in their value.
REQUIRED_KEYS = {
    "title": None,
    "config.step.login.title": None,
    "config.step.login.data.username": None,
    "config.step.login.data.password": None,
    "config.step.user.title": None,
    "config.step.user.data.authentication": None,
    "config.step.site.title": None,
    "config.step.site.data.site_reference": None,
    "config.step.reconfigure.title": None,
    "config.step.reconfigure.data.site_reference": None,
    "config.error.invalid_auth": None,
    "config.abort.already_configured": None,
    "config.abort.reauth_successful": None,
    "config.abort.wrong_account": None,
    "config.abort.no_sites": None,
    "config.abort.reconfigure_successful": None,
    "config.abort.reconfigure_not_supported": None,
    "options.step.init.title": None,
    "options.step.init.data.prices_timezone": None,
    "selector.prices_timezone.options.home_assistant": None,
    "selector.prices_timezone.options.utc": None,
    "services.get_prices.name": None,
    "services.get_prices.fields.config_entry_id.name": None,
    "services.get_prices.fields.start.name": None,
    "services.get_prices.fields.end.name": None,
    "exceptions.entry_not_found.message": "{entry_id}",
    "exceptions.entry_not_loaded.message": "{entry_id}",
    "exceptions.invalid_period.message": None,
}


def _flatten(data: dict, prefix: str = "") -> dict:
    """Flatten a nested dict into {"a.b.c": value} entries."""
    flat = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten(value, path))
        else:
            flat[path] = value
    return flat


def _load_flat(locale_file: Path) -> dict:
    return _flatten(json.loads(locale_file.read_text(encoding="utf-8")))


def test_locale_files_have_the_same_keys():
    """strings.json, en.json and nl.json define the same set of keys, aside from KNOWN_EXCEPTIONS."""
    flattened = {name: set(_load_flat(path)) for name, path in LOCALE_FILES.items()}
    all_keys = set().union(*flattened.values())

    for name, keys in flattened.items():
        allowed_missing = KNOWN_EXCEPTIONS.get(name, set())
        missing = all_keys - keys - allowed_missing
        assert not missing, f"{name} is missing keys: {sorted(missing)}"
        unexpectedly_present = allowed_missing & keys
        assert not unexpectedly_present, f"{name} defines keys that should stay absent: {sorted(unexpectedly_present)}"


def test_all_translation_values_are_non_empty_strings():
    """Every value in every locale file is a non-empty string (no raw keys/placeholders slipping through)."""
    for name, path in LOCALE_FILES.items():
        for dotted_path, value in _load_flat(path).items():
            assert isinstance(value, str), f"{name}: {dotted_path} is not a string ({value!r})"
            assert value.strip() != "", f"{name}: {dotted_path} is empty"


@pytest.mark.parametrize("dotted_path", REQUIRED_KEYS)
def test_required_key_present_in_every_locale_file(dotted_path):
    """Each required key exists in every locale file, with any documented required substring present."""
    required_substring = REQUIRED_KEYS[dotted_path]

    for name, path in LOCALE_FILES.items():
        flat = _load_flat(path)
        assert dotted_path in flat, f"{name}: missing required key {dotted_path!r}"
        if required_substring is not None:
            assert required_substring in flat[dotted_path], (
                f"{name}: {dotted_path} does not contain {required_substring!r}"
            )
