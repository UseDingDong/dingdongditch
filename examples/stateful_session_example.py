"""Deterministic retained-session example; run from the repository root."""

from pathlib import Path

from dingdongditch import (
    Action, ActionType, BrowserConfig, Expectation, ExpectationType, Locator,
    LocatorStrategy, Operation, StatefulSessionRuntime, UploadAuthorization,
)


ROOT = Path(__file__).resolve().parent
PAGE = (ROOT / "upload" / "upload_fixture.html").resolve()
FILE = (ROOT / "upload" / "harmless-upload.txt").resolve()
URL = PAGE.as_uri()


def main() -> None:
    runtime = StatefulSessionRuntime(default_idle_timeout_ms=60_000)
    session = runtime.open_session(BrowserConfig(headless=True))
    try:
        navigate = runtime.execute_operation(session.session_id, Operation(
            operation_id="navigate", url=URL,
            action=Action(type=ActionType.NAVIGATE),
            expectations=[Expectation(type=ExpectationType.URL, url_value=URL)],
        ))
        observation = runtime.observe_page(session.session_id)
        upload = runtime.execute_operation(session.session_id, Operation(
            operation_id="upload", url=URL,
            action=Action(
                type=ActionType.UPLOAD_FILE,
                locator=Locator(strategy=LocatorStrategy.TEST_ID, value="example-upload"),
                upload_authorization=UploadAuthorization(
                    (str(FILE),), allowed_files=(str(FILE),),
                ),
            ),
            expectations=[Expectation(
                type=ExpectationType.UPLOAD_FILE_COUNT,
                locator=Locator(strategy=LocatorStrategy.TEST_ID, value="example-upload"),
                file_count=1,
            )],
        ))
        after = runtime.observe_page(session.session_id)
        print({
            "session_id": session.session_id,
            "navigate": navigate.verdict,
            "upload": upload.verdict,
            "observations": [observation.observation.observation_id, after.observation.observation_id],
            "pages": len(runtime.inspect_pages(session.session_id)),
        })
    finally:
        runtime.close_session(session.session_id)


if __name__ == "__main__":
    main()
