from __future__ import annotations

from dingdongditch.authentication import AuthenticationCapability
from dingdongditch.backends.playwright_backend import PlaywrightBackend


def test_portable_cookie_localstorage_round_trip_into_new_context(tmp_path, fixture_url):
    exported_path = tmp_path / "portable-state.json"
    export_auth = AuthenticationCapability()
    first = PlaywrightBackend(authentication=export_auth)
    first.start()
    try:
        first.page.goto(fixture_url)
        first.page.evaluate("() => { localStorage.setItem('portable-theme', 'dark'); localStorage.setItem('password', 'excluded'); }")
        assert first._context is not None
        first._context.add_cookies([{"name": "portable-cookie", "value": "retained", "url": fixture_url}])
        receipt = export_auth.export_session(exported_path)
        assert receipt.status == "completed"
    finally:
        first.stop()

    import_auth = AuthenticationCapability()
    prepared = import_auth.prepare_session_import(exported_path)
    assert prepared.status == "completed"
    second = PlaywrightBackend(authentication=import_auth)
    second.start()
    try:
        second.page.goto(fixture_url)
        assert second.page.evaluate("() => localStorage.getItem('portable-theme')") == "dark"
        assert second.page.evaluate("() => localStorage.getItem('password')") is None
        assert second._context is not None
        assert any(cookie["name"] == "portable-cookie" for cookie in second._context.cookies())
    finally:
        second.stop()
