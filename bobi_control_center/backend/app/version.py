"""The application version, in one place.

`config.yaml` must carry the same string: the Supervisor keys its rebuilds off
the manifest version, so a code change that does not bump it may never reach a
running Home Assistant. Keeping the number here — rather than in `main.py` —
lets the adapters report it on `/api/bobi/connection` without importing the app.
"""

from __future__ import annotations

APP_NAME = "bobi-control-center"
APP_VERSION = "3.1.0"
