from __future__ import annotations

from app.config import Settings


def test_next_messaging_defaults_off_and_shadow_only():
    settings = Settings(_env_file=None)
    assert settings.next_runtime_enabled is False
    assert settings.next_messaging_enabled is False
    assert settings.next_messaging_dry_run is True


def test_messaging_flag_is_independent_from_event_runtime(monkeypatch):
    monkeypatch.setenv("BOBI_NEXT_RUNTIME_ENABLED", "true")
    settings = Settings(_env_file=None)
    assert settings.next_runtime_enabled is True
    assert settings.next_messaging_enabled is False
    assert settings.next_messaging_dry_run is True


def test_messaging_can_be_enabled_while_remaining_dry_run(monkeypatch):
    monkeypatch.setenv("BOBI_NEXT_MESSAGING_ENABLED", "true")
    settings = Settings(_env_file=None)
    assert settings.next_messaging_enabled is True
    assert settings.next_messaging_dry_run is True


def test_live_mutation_requires_separate_explicit_switch(monkeypatch):
    monkeypatch.setenv("BOBI_NEXT_MESSAGING_ENABLED", "true")
    monkeypatch.setenv("BOBI_NEXT_MESSAGING_DRY_RUN", "false")
    settings = Settings(_env_file=None)
    assert settings.next_messaging_enabled is True
    assert settings.next_messaging_dry_run is False
