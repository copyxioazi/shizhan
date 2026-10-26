from app.workers.react_analysis import (
    _normalise_path,
    _parse_tool_call,
    _truncate,
    react_messages,
)


def test_react_messages_lists_files_without_source():
    entries = [
        {"path": "app.py", "size": 3775},
        {"path": "verify/sql_injection.py", "size": 626},
    ]
    messages = react_messages("检查 SQL 注入", entries, max_steps=4)
    text = messages[-1]["content"]
    assert "app.py (3775 bytes)" in text
    assert "/src/verify/sql_injection.py" in text
    assert "最多进行 4 轮" in text
    assert "query = f" not in text


def test_parse_tool_call_handles_arguments():
    name, arguments = _parse_tool_call(
        {
            "id": "call_1",
            "function": {
                "name": "read_file",
                "arguments": '{"path": "app.py"}',
            },
        }
    )
    assert name == "read_file"
    assert arguments == {"path": "app.py"}

    name, arguments = _parse_tool_call(
        {"function": {"name": "search_code", "arguments": "not-json"}}
    )
    assert name == "search_code"
    assert arguments == {}


def test_normalise_path_and_truncate():
    assert _normalise_path("/src/app.py") == "app.py"
    assert _normalise_path("./verify/x.py") == "verify/x.py"
    assert _normalise_path(r"\src\config.py") == "config.py"
    assert _truncate("abcdef", 3) == "abc\n...[truncated]"
