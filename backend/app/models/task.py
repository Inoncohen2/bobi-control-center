"""Tasks and calendar events — only what Bobi management needs."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .common import Advanced, BobiModel


class Task(BobiModel):
    id: str
    title: str
    owner: str
    completed: bool = False
    due: datetime | None = None
    due_label: str | None = None
    list_name: str = "משימות"
    created_by: str = "בובי"
    advanced: Advanced = Field(default_factory=Advanced)


class CalendarEvent(BobiModel):
    id: str
    title: str
    owner: str
    start: datetime
    end: datetime | None = None
    day_label: str = Field(description="e.g. 'יום שלישי'")
    time_label: str = Field(description="e.g. '09:30'")
    location: str | None = None
    all_day: bool = False
    bobi_features: list[str] = Field(
        default_factory=list,
        description="Which Bobi capabilities react to this event.",
    )
    advanced: Advanced = Field(default_factory=Advanced)


class TaskList(BobiModel):
    open_tasks: list[Task]
    completed_tasks: list[Task]


class CalendarList(BobiModel):
    events: list[CalendarEvent]


class TaskUpdateRequest(BobiModel):
    completed: bool | None = None
    title: str | None = None
