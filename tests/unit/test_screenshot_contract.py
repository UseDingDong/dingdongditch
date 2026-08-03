from dingdongditch.contract.screenshot import (
    DesktopRedactionRegion,
    ScreenshotConfig,
    ScreenshotPolicy,
)
import pytest


def test_default_screenshot_policy_is_on_failure_and_describes_limits():
    config = ScreenshotConfig()
    assert config.policy == ScreenshotPolicy.ON_FAILURE
    assert config.describe()["max_per_operation"] == 4


def test_screenshot_policy_serializes_portable_artifact_root():
    config = ScreenshotConfig(policy=ScreenshotPolicy.BEFORE_AND_AFTER, artifact_root="artifacts/shots")
    assert config.describe()["artifact_root"] == "artifacts/shots"


def test_mandatory_redaction_requires_an_enabled_redaction_source():
    with pytest.raises(ValueError, match="requires password, selector, or desktop region"):
        ScreenshotConfig(
            redact_password_inputs=False,
            mandatory_redaction=True,
        ).validate()


@pytest.mark.parametrize(
    "selectors",
    [(["#secret"],), ("",), (123,)],
)
def test_sensitive_selectors_are_a_tuple_of_nonempty_css_strings(selectors):
    with pytest.raises(ValueError, match="sensitive_selectors"):
        ScreenshotConfig(sensitive_selectors=selectors).validate()


def test_desktop_redaction_regions_are_typed_and_serialized_exactly():
    region = DesktopRedactionRegion("account-number", 10, 20, 30, 40)
    config = ScreenshotConfig(
        redact_password_inputs=False,
        mandatory_redaction=True,
        desktop_redaction_regions=(region,),
    )
    config.validate()
    assert config.describe()["desktop_redaction_regions"] == [
        {"region_id": "account-number", "x": 10, "y": 20, "width": 30, "height": 40}
    ]


@pytest.mark.parametrize(
    "region",
    [
        DesktopRedactionRegion("", 0, 0, 1, 1),
        DesktopRedactionRegion("bad-x", -1, 0, 1, 1),
        DesktopRedactionRegion("bad-y", 0, -1, 1, 1),
        DesktopRedactionRegion("bad-width", 0, 0, 0, 1),
        DesktopRedactionRegion("bad-height", 0, 0, 1, 0),
        DesktopRedactionRegion("bool-coordinate", True, 0, 1, 1),
    ],
)
def test_desktop_redaction_region_rejects_ambiguous_coordinates(region):
    with pytest.raises(ValueError, match="desktop redaction"):
        region.validate()


def test_desktop_redaction_region_ids_must_be_unique():
    region = DesktopRedactionRegion("secret", 0, 0, 1, 1)
    with pytest.raises(ValueError, match="must be unique"):
        ScreenshotConfig(desktop_redaction_regions=(region, region)).validate()


def test_desktop_redaction_regions_must_be_an_immutable_typed_tuple():
    with pytest.raises(ValueError, match="desktop_redaction_regions"):
        ScreenshotConfig(desktop_redaction_regions=[{"x": 0}]).validate()
