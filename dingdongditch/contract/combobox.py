"""Deterministic custom combobox selection contract."""

from __future__ import annotations

from dataclasses import dataclass

from dingdongditch.contract.modes import TextMatchMode


@dataclass(frozen=True)
class ComboboxSelection:
    query: str
    expected_option: str
    match: TextMatchMode = TextMatchMode.EXACT
    clear_existing: bool = True
    dropdown_timeout_ms: int = 5_000

    def validate(self) -> None:
        if not isinstance(self.query, str):
            raise ValueError("combobox query must be a string")
        if not isinstance(self.expected_option, str) or not self.expected_option.strip():
            raise ValueError("combobox expected_option must be a non-empty string")
        if not isinstance(self.match, TextMatchMode):
            raise ValueError("combobox match must be a TextMatchMode")
        if not isinstance(self.clear_existing, bool):
            raise ValueError("combobox clear_existing must be boolean")
        if not isinstance(self.dropdown_timeout_ms, int) or isinstance(self.dropdown_timeout_ms, bool) or not 1 <= self.dropdown_timeout_ms <= 30_000:
            raise ValueError("combobox dropdown_timeout_ms must be between 1 and 30000")

    def describe(self) -> dict[str, object]:
        return {
            "query": self.query,
            "expected_option": self.expected_option,
            "match": self.match.value,
            "clear_existing": self.clear_existing,
            "dropdown_timeout_ms": self.dropdown_timeout_ms,
        }
