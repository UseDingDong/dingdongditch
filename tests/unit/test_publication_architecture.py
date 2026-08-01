from __future__ import annotations

import ast
from pathlib import Path


def test_runtime_package_has_no_direct_path_publication():
    root = Path(__file__).resolve().parents[2] / "dingdongditch"
    violations = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"write_text", "write_bytes"}
            ):
                violations.append(f"{path.relative_to(root)}:{node.lineno}")
    assert violations == [], (
        "externally visible files must use the shared atomic publication contract: "
        + ", ".join(violations)
    )
