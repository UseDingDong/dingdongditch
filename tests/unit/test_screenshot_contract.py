from dingdongditch.contract.screenshot import ScreenshotConfig, ScreenshotPolicy


def test_default_screenshot_policy_is_on_failure_and_describes_limits():
    config = ScreenshotConfig()
    assert config.policy == ScreenshotPolicy.ON_FAILURE
    assert config.describe()["max_per_operation"] == 4


def test_screenshot_policy_serializes_portable_artifact_root():
    config = ScreenshotConfig(policy=ScreenshotPolicy.BEFORE_AND_AFTER, artifact_root="artifacts/shots")
    assert config.describe()["artifact_root"] == "artifacts/shots"
