"""Shared match-mode enums for expectations and wait conditions."""

from __future__ import annotations

from enum import Enum


class UrlMatchMode(str, Enum):
    EXACT = "exact"
    CONTAINS = "contains"


class TextMatchMode(str, Enum):
    CONTAINS = "contains"
    EXACT = "exact"
