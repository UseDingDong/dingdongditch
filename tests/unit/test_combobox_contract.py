import json
import pytest
from dingdongditch import Action, ActionType, ComboboxSelection, Locator, LocatorStrategy
from dingdongditch.contract.modes import TextMatchMode
from dingdongditch.plan_json import load_plan_json_text

def test_combobox_contract_and_description():
    action=Action(type=ActionType.SELECT_COMBOBOX_OPTION,locator=Locator(strategy=LocatorStrategy.TEST_ID,value="city"),combobox_selection=ComboboxSelection("New York","New York, New York, United States",TextMatchMode.EXACT))
    action.validate(); assert action.describe()["combobox"]["expected_option"].startswith("New York,")

def test_combobox_requires_typed_request():
    with pytest.raises(ValueError):
        Action(type=ActionType.SELECT_COMBOBOX_OPTION,locator=Locator(strategy=LocatorStrategy.TEST_ID,value="city")).validate()

def test_combobox_plan_json_and_existing_select_unchanged():
    plan=load_plan_json_text(json.dumps({"plan_id":"c","operations":[{"operation_id":"c","url":"https://example.test","action":{"type":"select_combobox_option","locator":{"strategy":"test_id","value":"city"},"combobox":{"query":"New York","expected_option":"New York, New York, United States","match":"exact"}},"expectations":[]}]}))
    assert plan.operations[0].action.combobox_selection.match == TextMatchMode.EXACT
    normal=Action(type=ActionType.SELECT_OPTION,locator=Locator(strategy=LocatorStrategy.TEST_ID,value="native"),option_value="x")
    normal.validate()
