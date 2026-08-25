"""Settings screen models.

Secret values are *never* serialised. ``SettingField.value`` for a field whose
``secret`` flag is true always carries the mask constant instead.
"""

from __future__ import annotations

from pydantic import Field

from .common import BobiModel

MASK = "••••••••"


class SettingField(BobiModel):
    key: str
    label: str
    type: str = Field(description="'text' | 'bool' | 'select' | 'time' | 'info' | 'secret'")
    value: object | None = None
    options: list[str] = Field(default_factory=list)
    help: str | None = None
    secret: bool = False
    editable: bool = True


class SettingsSection(BobiModel):
    id: str
    title: str
    description: str = ""
    icon: str = "settings"
    fields: list[SettingField] = Field(default_factory=list)


class SettingsResponse(BobiModel):
    sections: list[SettingsSection]
    read_only: bool = True
    note: str = "בשלב זה ההגדרות הן לצפייה בלבד ואינן משפיעות על מערכת אמיתית."
