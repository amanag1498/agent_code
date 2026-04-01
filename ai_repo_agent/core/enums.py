"""Shared enums."""

from __future__ import annotations

from enum import StrEnum


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"
    UNKNOWN = "unknown"


class FindingStatus(StrEnum):
    OPEN = "open"
    FIXED = "fixed"
    UNCHANGED = "unchanged"
    REGRESSED = "regressed"


class DeltaType(StrEnum):
    NEW = "new"
    FIXED = "fixed"
    UNCHANGED = "unchanged"
    REGRESSED = "regressed"


class Verdict(StrEnum):
    TRUE_POSITIVE = "true_positive"
    LIKELY_TRUE_POSITIVE = "likely_true_positive"
    UNCERTAIN = "uncertain"
    LIKELY_FALSE_POSITIVE = "likely_false_positive"
    FALSE_POSITIVE = "false_positive"


class SeverityOverride(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"
    UNCHANGED = "unchanged"


class ReviewTargetType(StrEnum):
    FINDING = "finding"
    SNAPSHOT = "snapshot"
    DIFF = "diff"

