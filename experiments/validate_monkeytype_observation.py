"""Read-only headed validation of PageObservation against Monkeytype."""

from __future__ import annotations

import json
from pathlib import Path

from dingdongditch import BrowserConfig, BrowserProfile, observe_page
from dingdongditch.backends.playwright_backend import PlaywrightBackend


def main() -> None:
    backend = PlaywrightBackend(
        BrowserConfig(headless=False, profile=BrowserProfile.DINGDONG)
    )
    output = Path("artifacts/monkeytype_page_observation.json")
    try:
        backend.start()
        backend.page.goto(
            "https://monkeytype.com/", wait_until="domcontentloaded", timeout=60_000
        )
        backend.page.wait_for_timeout(4_000)
        observation = observe_page(backend)
        controls = [
            element
            for element in observation.interactive_elements
            if (element.get("accessible_name") or "").strip().lower() in {"time", "words"}
            or (element.get("visible_text") or "").strip().lower() in {"time", "words"}
        ]
        ids = {item["element_id"] for item in controls}
        report = {
            "observation_id": observation.observation_id,
            "url": observation.url,
            "title": observation.title,
            "controls": controls,
            "relationships": [
                relationship
                for relationship in observation.spatial_relationships
                if relationship["source_element_id"] in ids
                and relationship["target_element_id"] in ids
            ],
            "diagnostics": observation.diagnostics,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
    finally:
        backend.stop()


if __name__ == "__main__":
    main()
