"""Runtime guards for Home Assistant App option loading."""

from __future__ import annotations

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]


def test_run_sh_loads_options_without_supervisor_api() -> None:
    """External auth options must not depend on hassio/Supervisor API access."""
    run_sh = (APP_ROOT / "run.sh").read_text(encoding="utf-8")

    assert "/data/options.json" in run_sh
    assert "bashio::supervisor.ping" not in run_sh
    assert "bashio::config 'external_hostname'" in run_sh
    assert "bashio::config 'external_password_hash'" in run_sh
