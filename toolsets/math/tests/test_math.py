from __future__ import annotations

from toolsets.math.src.lambda_handler import AddParams, AddResult, add, handler


def test_add_unit():
    result = add(AddParams(x=1, y=2))
    assert isinstance(result, AddResult)
    assert result.value == 3


def test_describe_tools_contract():
    event = {"action": "describe_tools"}
    resp = handler(event, None)
    assert "result" in resp
    tools = resp["result"]["tools"]
    names = {t["name"] for t in tools}
    assert "add" in names


def test_invoke_contract():
    event = {"action": "invoke", "method": "add", "params": {"x": 2, "y": 5}}
    resp = handler(event, None)
    assert resp.get("result") == {"value": 7}
