"""Typed, one-shot DOM element state captured at one verification boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


LEGACY_ATTRIBUTE_NAMES = (
    "data-state",
    "aria-pressed",
    "value",
    "class",
    "id",
    "data-testid",
    "data-purpose",
    "data-value",
    "data-agree",
    "data-prefers",
)


class SnapshotAvailability(str, Enum):
    AVAILABLE = "available"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ElementStateSnapshot:
    """Internal typed snapshot; never reused across observation boundaries."""

    availability: SnapshotAvailability
    match_count: int
    exists: bool
    ambiguous: bool = False
    visible: bool | None = None
    enabled: bool | None = None
    in_viewport: bool | None = None
    checked: bool | None = None
    selected: bool | None = None
    focused: bool | None = None
    text: str | None = None
    value: str | None = None
    role: str | None = None
    bounding_box: dict[str, float] | None = None
    attributes: dict[str, str | None] = field(default_factory=dict)
    target_resolution: dict[str, Any] | None = None
    collection_mode: str = "atomic"
    error: str | None = None

    def to_legacy_state(self) -> dict[str, Any]:
        """Return the pre-optimization public/evidence dictionary shape."""
        if self.availability == SnapshotAvailability.MISSING:
            return {
                "match_count": 0,
                "exists": False,
                "target_resolution": self.target_resolution,
            }
        if self.availability == SnapshotAvailability.AMBIGUOUS:
            return {
                "match_count": self.match_count,
                "exists": True,
                "ambiguous": True,
                "target_resolution": self.target_resolution,
            }
        return {
            "match_count": self.match_count,
            "exists": self.exists,
            "visible": self.visible,
            "enabled": self.enabled,
            "in_viewport": self.in_viewport,
            "checked": self.checked,
            "focused": self.focused,
            "text": self.text or "",
            "attributes": dict(self.attributes),
            "target_resolution": self.target_resolution,
        }


class AtomicSnapshotUnsupported(RuntimeError):
    """The browser explicitly reported that atomic DOM evaluation is unsupported."""


ATOMIC_ELEMENT_SNAPSHOT_JS = """
(el, attributeNames) => {
  if (!el || el.nodeType !== Node.ELEMENT_NODE) {
    return {supported: false, error: "resolved target is not an Element"};
  }

  const rect = el.getBoundingClientRect();
  const style = window.getComputedStyle(el);
  const connected = el.isConnected === true;
  const visible = connected
    && style.visibility !== "hidden"
    && style.visibility !== "collapse"
    && rect.width > 0
    && rect.height > 0;
  const viewportHeight =
    window.innerHeight || document.documentElement.clientHeight;
  const viewportWidth =
    window.innerWidth || document.documentElement.clientWidth;
  const inViewport = connected
    && !(rect.width === 0 && rect.height === 0)
    && rect.bottom > 0
    && rect.right > 0
    && rect.top < viewportHeight
    && rect.left < viewportWidth;

  let disabled = false;
  try {
    disabled = el.matches(":disabled");
  } catch (_) {
    disabled = false;
  }
  let ariaNode = el;
  while (ariaNode && ariaNode.nodeType === Node.ELEMENT_NODE) {
    if ((ariaNode.getAttribute("aria-disabled") || "").toLowerCase() === "true") {
      disabled = true;
      break;
    }
    ariaNode = ariaNode.parentElement;
  }

  const tag = el.tagName.toLowerCase();
  const inputType = tag === "input"
    ? (el.getAttribute("type") || "text").toLowerCase()
    : null;
  const checkable = tag === "input"
    && (inputType === "checkbox" || inputType === "radio");
  const selectable = tag === "option"
    || el.hasAttribute("aria-selected");
  const valueBearing =
    tag === "input" || tag === "textarea" || tag === "select";

  const attributes = {};
  for (const name of attributeNames) {
    attributes[name] = el.getAttribute(name);
  }
  if (valueBearing) {
    attributes.value = String(el.value);
  }

  let role = el.getAttribute("role");
  if (!role) {
    if (tag === "button") role = "button";
    else if (tag === "a" && el.hasAttribute("href")) role = "link";
    else if (tag === "select") role = "combobox";
    else if (tag === "textarea") role = "textbox";
    else if (tag === "input") {
      if (inputType === "checkbox") role = "checkbox";
      else if (inputType === "radio") role = "radio";
      else if (inputType !== "hidden") role = "textbox";
    }
  }

  return {
    supported: true,
    connected,
    visible,
    enabled: !disabled,
    in_viewport: inViewport,
    checked: checkable ? Boolean(el.checked) : null,
    selected: selectable
      ? (tag === "option"
          ? Boolean(el.selected)
          : (el.getAttribute("aria-selected") || "").toLowerCase() === "true")
      : null,
    focused: document.activeElement === el,
    text: visible ? String(el.innerText || "") : String(el.textContent || ""),
    value: valueBearing ? String(el.value) : null,
    role,
    bounding_box: connected ? {
      x: rect.x,
      y: rect.y,
      width: rect.width,
      height: rect.height,
    } : null,
    attributes,
  };
}
"""
