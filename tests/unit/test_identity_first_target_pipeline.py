from dingdongditch.backends.target_resolver import identity_locator
from dingdongditch.contract.operation import Locator, LocatorStrategy
from dingdongditch.contract.target import ConstraintType, TargetConstraint


def test_identity_excludes_temporary_interaction_state():
    locator = Locator(
        strategy=LocatorStrategy.TEST_ID,
        value="stable-id",
        constraints=(
            TargetConstraint(type=ConstraintType.VISIBLE, visible=True),
            TargetConstraint(type=ConstraintType.ENABLED, enabled=True),
        ),
    )

    stable = identity_locator(locator)

    assert stable.value == "stable-id"
    assert stable.constraints == ()
    assert len(locator.constraints) == 2
