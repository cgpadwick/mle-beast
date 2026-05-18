# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Tests for mle_beast.settings."""

from __future__ import annotations

from dataclasses import fields

import pytest

from mle_beast import settings as settings_mod
from mle_beast.settings import (
    Settings,
    get_settings,
    load_settings,
    reload_settings,
    save_settings,
)


class _StubDB:
    """Minimal in-memory stand-in for the Database object used by settings."""

    def __init__(self, initial: dict | None = None):
        self._row = dict(initial) if initial else None

    def get_settings(self):
        return self._row

    def update_settings(self, data: dict):
        self._row = dict(data)


class TestSettingsDataclass:
    def test_defaults_construct(self):
        s = Settings()
        # A few representative defaults — guards against silent type/value drift
        assert s.model_provider == ""
        assert s.model_name == ""
        assert s.max_tokens == 65536
        assert s.training_timeout == 1800
        assert s.log_level == "INFO"

    def test_to_dict_round_trips_every_field(self):
        s = Settings()
        d = s.to_dict()
        assert set(d.keys()) == {f.name for f in fields(Settings)}
        assert Settings.from_dict(d) == s

    def test_from_dict_filters_unknown_keys(self):
        s = Settings.from_dict({"model_name": "gpt-5", "garbage_key": 42})
        assert s.model_name == "gpt-5"
        assert not hasattr(s, "garbage_key")

    def test_from_dict_accepts_partial_data(self):
        # Missing keys should fall back to defaults.
        s = Settings.from_dict({"max_tokens": 1024})
        assert s.max_tokens == 1024
        assert s.training_timeout == Settings().training_timeout


class TestPersistenceHelpers:
    def test_load_settings_returns_defaults_when_row_missing(self):
        db = _StubDB(initial=None)
        s = load_settings(db)
        assert s == Settings()

    def test_load_settings_reads_row(self):
        db = _StubDB(initial={"model_name": "custom-model", "max_tokens": 8000})
        s = load_settings(db)
        assert s.model_name == "custom-model"
        assert s.max_tokens == 8000

    def test_save_settings_writes_all_fields(self):
        db = _StubDB(initial=None)
        s = Settings(model_name="x", log_level="DEBUG")
        save_settings(db, s)
        # Round-trip through the stub.
        assert db._row is not None
        assert db._row["model_name"] == "x"
        assert db._row["log_level"] == "DEBUG"


class TestSingleton:
    @pytest.fixture(autouse=True)
    def _isolate(self, monkeypatch):
        # Reset the module-level cache so every test starts fresh, and stub
        # out the lazy db import inside get_settings/reload_settings.
        monkeypatch.setattr(settings_mod, "_settings", None)
        stub = _StubDB(initial={"model_name": "stub-default"})
        monkeypatch.setattr(
            "mle_beast.db.get_database",
            lambda: stub,
        )
        # Hand the stub back so tests can manipulate the row directly.
        yield stub
        monkeypatch.setattr(settings_mod, "_settings", None)

    def test_get_settings_loads_once(self, _isolate):
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
        assert s1.model_name == "stub-default"

    def test_get_settings_caches_even_if_db_changes(self, _isolate):
        get_settings()  # primes cache
        _isolate._row = {"model_name": "changed-after-cache"}
        s = get_settings()
        # Cached — should NOT reflect the post-load change.
        assert s.model_name == "stub-default"

    def test_reload_settings_picks_up_changes(self, _isolate):
        get_settings()
        _isolate._row = {"model_name": "fresh-read"}
        s = reload_settings()
        assert s.model_name == "fresh-read"
        # And subsequent get_settings sees the new value.
        assert get_settings().model_name == "fresh-read"
