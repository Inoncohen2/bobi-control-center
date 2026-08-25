"""Diagnostics, regression test suites and the audit log."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .common import BobiModel, Severity, Source


class DiagnosticIssue(BobiModel):
    id: str
    severity: Severity
    title: str = Field(description="Hebrew, human readable. Not a stack trace.")
    description: str
    component: str
    first_seen: datetime
    last_seen: datetime
    occurrences: int = 1
    suggested_action: str | None = None
    technical_details: str | None = Field(
        default=None,
        description="Collapsed by default in the UI.",
    )


class DiagnosticsReport(BobiModel):
    issues: list[DiagnosticIssue]
    ok_count: int = 0
    warning_count: int = 0
    error_count: int = 0
    generated_at: datetime


class TestCase(BobiModel):
    id: str
    name: str
    passed: bool
    duration_ms: int = 0
    message: str | None = None


class TestSuite(BobiModel):
    id: str
    name: str
    description: str
    total: int
    passed: int
    failed: int
    duration_ms: int
    last_run: datetime | None = None
    cases: list[TestCase] = Field(default_factory=list)


class TestReport(BobiModel):
    suites: list[TestSuite]
    total: int
    passed: int
    failed: int
    last_run: datetime | None = None
    running: bool = False
    note: str = Field(
        default="בדיקות אלו הן הדמיה בלבד ואינן נוגעות במערכת אמיתית.",
        description="Phase 1 suites are mock only.",
    )


class AuditEntry(BobiModel):
    id: str
    timestamp: datetime
    user: str
    operation: str = Field(description="'create' | 'update' | 'delete' | 'toggle' | 'probe'")
    operation_label: str
    resource_type: str
    resource_id: str
    resource_label: str | None = None
    before: dict[str, object] | None = None
    after: dict[str, object] | None = None
    success: bool = True
    source: Source = Source.WEB


class AuditLog(BobiModel):
    entries: list[AuditEntry]
    total: int
