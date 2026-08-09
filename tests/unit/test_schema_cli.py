from __future__ import annotations

import json

from jsonschema import Draft202012Validator
import pytest

import dingdongditch as dingdong
from dingdongditch.cli import main


def test_schema_list_is_machine_readable_json(capsys):
    assert main(["schema", "list"]) == 0
    values = json.loads(capsys.readouterr().out)
    assert values == list(dingdong.public_schema_names())


@pytest.mark.parametrize("target", dingdong.public_schema_names())
def test_schema_target_writes_valid_schema_to_stdout(target, capsys):
    assert main(["schema", target]) == 0
    schema = json.loads(capsys.readouterr().out)
    Draft202012Validator.check_schema(schema)
    assert schema == dingdong.published_schema_resource(target)


def test_schema_output_file(tmp_path, capsys):
    output = tmp_path / "plan.schema.json"
    assert main(["schema", "plan-document", "--output", str(output)]) == 0
    assert capsys.readouterr().out == ""
    assert json.loads(output.read_text(encoding="utf-8")) == dingdong.execution_schema()
