from pathlib import Path
from dingdongditch import Action,ActionType,BrowserConfig,ComboboxSelection,Expectation,ExpectationType,Locator,LocatorStrategy,Operation,StatefulSessionRuntime,UploadAuthorization,Verdict
from dingdongditch.contract.modes import TextMatchMode

FIX=Path(__file__).parents[1]/"fixtures"/"local_test_app"
FILE=(FIX/"upload-one.txt").resolve()
def tid(v): return Locator(strategy=LocatorStrategy.TEST_ID,value=v)
def combo(url,op,target,query,expected,match=TextMatchMode.EXACT): return Operation(operation_id=op,url=url,action=Action(type=ActionType.SELECT_COMBOBOX_OPTION,locator=tid(target),combobox_selection=ComboboxSelection(query,expected,match)),expectations=[])

def test_retained_session_modern_ats_end_to_end(fixture_url):
    url=fixture_url.replace("index.html","modern_ats_fixture.html"); rt=StatefulSessionRuntime(); s=rt.open_session(BrowserConfig(headless=True))
    try:
        rt.execute_operation(s.session_id,Operation(operation_id="nav",url=url,action=Action(type=ActionType.NAVIGATE),expectations=[Expectation(type=ExpectationType.URL,url_value=url)]))
        rt.execute_operation(s.session_id,Operation(operation_id="name",url=url,action=Action(type=ActionType.FILL,locator=tid("candidate-name"),text="Jordan Bennett"),expectations=[]))
        city=rt.execute_operation(s.session_id,combo(url,"city","city","New York","New York, New York, United States")); assert city.receipt.action_evidence["combobox"]["verification_result"]=="pass"
        country=rt.execute_operation(s.session_id,combo(url,"country","country","United States","United States")); assert country.receipt.action_evidence["combobox"]["verification_result"]=="pass"
        answer=rt.execute_operation(s.session_id,combo(url,"answer","answer","","Yes")); assert answer.receipt.action_evidence["combobox"]["selected_option"]=="Yes"
        upload=rt.execute_operation(s.session_id,Operation(operation_id="upload",url=url,action=Action(type=ActionType.UPLOAD_FILE,locator=Locator(strategy=LocatorStrategy.CSS,value="#resume-upload"),upload_authorization=UploadAuthorization((str(FILE),),allowed_files=(str(FILE),))),expectations=[Expectation(type=ExpectationType.TEXT,locator=tid("resume-chip"),text_value=FILE.name)]))
        assert upload.verdict==Verdict.VERIFIED.value
        ue=upload.receipt.action_evidence["upload"]; assert ue["execution_result"]=="verified" and ue["verification_signals"]["fresh_visible_filename"]
        observed=rt.observe_page(s.session_id); text=" ".join(str(x.get("text",x)) if isinstance(x,dict) else str(x) for x in observed.observation.visible_text)
        assert "New York, New York, United States" in text and FILE.name in text
    finally: assert rt.close_session(s.session_id).status.value=="closed"

def test_combobox_fail_closed_cases_and_native_select_regression(fixture_url):
    url=fixture_url.replace("index.html","modern_ats_fixture.html"); rt=StatefulSessionRuntime();s=rt.open_session()
    try:
        rt.execute_operation(s.session_id,Operation(operation_id="nav",url=url,action=Action(type=ActionType.NAVIGATE),expectations=[]))
        ambiguous=rt.execute_operation(s.session_id,combo(url,"amb","city","New York","New York",TextMatchMode.CONTAINS)); assert ambiguous.receipt.failure_kind=="ambiguous_option"
        missing=rt.execute_operation(s.session_id,combo(url,"none","country","Atlantis","Atlantis")); assert missing.receipt.failure_kind in {"dropdown_not_opened","no_matching_option"}
        broken=rt.execute_operation(s.session_id,combo(url,"broken","broken","Chosen","Chosen")); assert broken.receipt.failure_kind=="selection_not_persisted"
    finally: rt.close_session(s.session_id)
