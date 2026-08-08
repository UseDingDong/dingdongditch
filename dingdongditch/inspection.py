"""Read-only target inspection for an already active host-owned session."""

from __future__ import annotations

from typing import Any

from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.operation import Locator
from dingdongditch.contract.observation import PageObservation, PageObservationOptions


def inspect_target(
    backend: PlaywrightBackend,
    locator: Locator,
    *,
    frame: Locator | None = None,
    frame_path: tuple[Locator, ...] = (),
) -> dict[str, Any]:
    if not backend.is_started:
        raise RuntimeError("target inspection requires an active host-owned backend")
    locator.validate()
    if frame is not None:
        frame.validate()
    if frame is not None and frame_path:
        raise ValueError("frame and frame_path are mutually exclusive")
    for hop in frame_path:
        hop.validate()
    state = backend.read_element_state(locator, frame=frame, frame_path=frame_path)
    return {
        "page": {
            "url": backend.page.url,
            "browser": backend.browser_environment(),
        },
        "locator": locator.describe(),
        "frame": frame.describe() if frame else None,
        "frame_path": [hop.describe() for hop in frame_path],
        "match_count": state.get("match_count"),
        "exists": state.get("exists"),
        "ambiguous": state.get("ambiguous", False),
        "visible": state.get("visible"),
        "enabled": state.get("enabled"),
        "text": state.get("text"),
        "target_resolution": state.get("target_resolution"),
    }


def list_known_pages(backend: PlaywrightBackend) -> list[dict[str, Any]]:
    """Return the stable, read-only page registry for an active session."""
    if not backend.is_started:
        raise RuntimeError("page inspection requires an active host-owned backend")
    return backend.list_pages()


def inspect_known_page(
    backend: PlaywrightBackend, page_id: str
) -> dict[str, Any] | None:
    """Inspect one known page without switching or dispatching."""
    if not backend.is_started:
        raise RuntimeError("page inspection requires an active host-owned backend")
    return backend.inspect_page(page_id)


def list_dialog_history(backend: PlaywrightBackend) -> list[dict[str, Any]]:
    """Read-only native-dialog history for an active host-owned session."""
    if not backend.is_started:
        raise RuntimeError("dialog inspection requires an active host-owned backend")
    return backend.list_dialog_history()


def observe_page(
    backend: PlaywrightBackend,
    options: PageObservationOptions | None = None,
) -> PageObservation:
    """Observe an active host-owned page without dispatching any action."""
    if not backend.is_started:
        raise RuntimeError("page observation requires an active host-owned backend")
    return backend.observe_page(options)
