import platform
import sys
from pathlib import Path

import pytest

from dingdongditch.backends.windows_desktop_backend import (
    DesktopBackendError,
    OwnedWindow,
    WindowsDesktopBackend,
)
from dingdongditch.contract.desktop import (
    ApprovedApplication,
    DesktopActionType,
    WindowSelector,
)
from dingdongditch.contract.screenshot import (
    DesktopRedactionRegion,
    ScreenshotConfig,
    ScreenshotPolicy,
)


requires_windows_desktop = pytest.mark.skipif(
    sys.platform != "win32", reason="requires the Windows desktop backend"
)


def test_capabilities_are_honest_and_allowlisted():
    caps = WindowsDesktopBackend.capabilities()
    assert caps["domain"] == "windows_desktop"
    assert caps["arbitrary_commands"] is False
    assert caps["coordinate_primary_control"] is False
    assert set(caps["approved_applications"]) == {"explorer", "notepad"}
    assert set(caps["actions"]) == {item.value for item in DesktopActionType}


def test_unsupported_platform_is_gated(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    with pytest.raises(DesktopBackendError) as raised:
        WindowsDesktopBackend()
    assert raised.value.failure_kind == "unsupported_platform"


@requires_windows_desktop
def test_window_discovery_and_uniqueness(monkeypatch, tmp_path):
    backend = WindowsDesktopBackend(artifact_root=tmp_path)
    backend._owned_windows = {
        1: OwnedWindow(1, "notepad", 101, "test"),
        2: OwnedWindow(2, "notepad", 102, "test"),
    }
    monkeypatch.setattr(
        backend,
        "_window_info",
        lambda handle: {
            "window_handle": handle,
            "window_title": f"Note {handle} - Notepad",
            "process_id": 100 + handle,
        },
    )
    selector = WindowSelector(application=ApprovedApplication.NOTEPAD)
    assert backend.find_windows(selector) == [1, 2]
    with pytest.raises(DesktopBackendError) as raised:
        backend._resolve_window(selector, 100)
    assert raised.value.failure_kind == "window_not_unique"


@requires_windows_desktop
def test_bounded_wait_reports_timeout(tmp_path):
    backend = WindowsDesktopBackend(artifact_root=tmp_path)
    with pytest.raises(DesktopBackendError) as raised:
        backend._wait_until(
            lambda: False, timeout_ms=100, failure_kind="test_timeout"
        )
    assert raised.value.failure_kind == "test_timeout"


@requires_windows_desktop
def test_safe_close_ownership_is_ledger_based(tmp_path):
    backend = WindowsDesktopBackend(artifact_root=tmp_path)
    assert backend.owned_window_handles == ()
    backend._owned_windows[44] = OwnedWindow(44, "notepad", 55, "test")
    assert backend.owned_window_handles == (44,)
    assert backend._owned_windows[44].source == "test"


@requires_windows_desktop
def test_mandatory_desktop_redaction_fails_before_capture_or_publication(
    monkeypatch, tmp_path
):
    backend = WindowsDesktopBackend(artifact_root=tmp_path)
    grab_called = False

    def forbidden_grab(*args, **kwargs):
        nonlocal grab_called
        grab_called = True
        raise AssertionError("desktop capture must not start")

    import PIL.ImageGrab

    monkeypatch.setattr(PIL.ImageGrab, "grab", forbidden_grab)
    with pytest.raises(DesktopBackendError) as raised:
        backend.capture_screenshot(
            plan_id="mandatory",
            operation_id="operation",
            reason="failure",
            config=ScreenshotConfig(
                policy=ScreenshotPolicy.ALWAYS,
                artifact_root=str(tmp_path),
                mandatory_redaction=True,
            ),
        )
    assert raised.value.failure_kind == "screenshot_redaction_failed"
    assert "requires at least one" in str(raised.value)
    assert grab_called is False
    assert list(tmp_path.iterdir()) == []


@requires_windows_desktop
def test_nonmandatory_desktop_capture_behavior_is_preserved(monkeypatch, tmp_path):
    backend = WindowsDesktopBackend(artifact_root=tmp_path)

    class FakeImage:
        width = 640
        height = 480

        @staticmethod
        def save(path, image_format):
            assert image_format == "PNG"
            Path(path).write_bytes(b"complete-png-fixture")

    import PIL.ImageGrab

    monkeypatch.setattr(
        PIL.ImageGrab, "grab", lambda *, all_screens: FakeImage()
    )
    result = backend.capture_screenshot(
        plan_id="ordinary",
        operation_id="operation",
        reason="failure",
        config=ScreenshotConfig(
            policy=ScreenshotPolicy.ON_FAILURE,
            artifact_root=str(tmp_path),
            mandatory_redaction=False,
        ),
    )
    assert result["width"] == 640
    assert result["height"] == 480
    assert Path(result["path"]).read_bytes() == b"complete-png-fixture"
    assert result["redaction_status"] == "not_requested"
    assert result["redacted_regions"] == []


@requires_windows_desktop
def test_declared_desktop_regions_are_blacked_out_and_receipted(monkeypatch, tmp_path):
    from PIL import Image, ImageGrab

    backend = WindowsDesktopBackend(artifact_root=tmp_path)
    source = Image.new("RGB", (8, 6), (255, 0, 0))
    monkeypatch.setattr(ImageGrab, "grab", lambda *, all_screens: source.copy())
    regions = (
        DesktopRedactionRegion("first", 1, 1, 3, 2),
        DesktopRedactionRegion("second", 6, 4, 2, 2),
    )
    result = backend.capture_screenshot(
        plan_id="redacted",
        operation_id="operation",
        reason="after_success",
        config=ScreenshotConfig(
            policy=ScreenshotPolicy.ALWAYS,
            artifact_root=str(tmp_path),
            mandatory_redaction=True,
            desktop_redaction_regions=regions,
        ),
    )
    with Image.open(result["path"]) as published:
        assert published.getpixel((1, 1)) == (0, 0, 0)
        assert published.getpixel((3, 2)) == (0, 0, 0)
        assert published.getpixel((6, 4)) == (0, 0, 0)
        assert published.getpixel((7, 5)) == (0, 0, 0)
        assert published.getpixel((0, 0)) == (255, 0, 0)
        assert published.getpixel((4, 2)) == (255, 0, 0)
    assert result["redaction_status"] == "applied"
    assert result["redaction_method"] == "caller_declared_solid_pixel_regions"
    assert result["redaction_color"] == "#000000"
    assert result["redacted_regions"] == [region.describe() for region in regions]


@pytest.mark.parametrize(
    "region",
    [
        DesktopRedactionRegion("past-right", 7, 0, 2, 1),
        DesktopRedactionRegion("past-bottom", 0, 5, 1, 2),
    ],
)
@requires_windows_desktop
def test_out_of_bounds_desktop_region_fails_without_publication(
    monkeypatch, tmp_path, region
):
    from PIL import Image, ImageGrab

    backend = WindowsDesktopBackend(artifact_root=tmp_path)
    monkeypatch.setattr(
        ImageGrab, "grab", lambda *, all_screens: Image.new("RGB", (8, 6), "white")
    )
    with pytest.raises(DesktopBackendError) as raised:
        backend.capture_screenshot(
            plan_id="redacted",
            operation_id="operation",
            reason="failure",
            config=ScreenshotConfig(
                artifact_root=str(tmp_path),
                mandatory_redaction=True,
                desktop_redaction_regions=(region,),
            ),
        )
    assert raised.value.failure_kind == "screenshot_redaction_failed"
    assert region.region_id in str(raised.value)
    assert list(tmp_path.iterdir()) == []


@requires_windows_desktop
def test_masking_failure_is_explicit_and_never_publishes(monkeypatch, tmp_path):
    from PIL import Image, ImageDraw, ImageGrab

    backend = WindowsDesktopBackend(artifact_root=tmp_path)
    monkeypatch.setattr(
        ImageGrab, "grab", lambda *, all_screens: Image.new("RGB", (8, 6), "white")
    )
    monkeypatch.setattr(
        ImageDraw, "Draw", lambda image: (_ for _ in ()).throw(RuntimeError("mask failed"))
    )
    with pytest.raises(DesktopBackendError) as raised:
        backend.capture_screenshot(
            plan_id="redacted",
            operation_id="operation",
            reason="failure",
            config=ScreenshotConfig(
                artifact_root=str(tmp_path),
                mandatory_redaction=True,
                desktop_redaction_regions=(
                    DesktopRedactionRegion("secret", 0, 0, 1, 1),
                ),
            ),
        )
    assert raised.value.failure_kind == "screenshot_redaction_failed"
    assert "mask failed" in str(raised.value)
    assert list(tmp_path.iterdir()) == []
