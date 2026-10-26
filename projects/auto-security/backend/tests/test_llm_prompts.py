import pytest
from app.workers.llm_prompts import (
    LLMValidationError,
    parse_code_findings,
    parse_general_plan,
    parse_report_output,
    parse_verification_plan,
    verification_messages,
    verification_retry_messages,
)

APP_CONTENT = """line1
query = f"SELECT * FROM items WHERE name LIKE '%{q}%'"
line3
"""
FILES = [("app.py", APP_CONTENT)]


def _candidate(**overrides):
    value = {
        "vuln_title": "SQL 注入",
        "risk_level": "high",
        "file_path": "app.py",
        "line_no": 2,
        "impact_text": "影响",
        "condition_text": "条件",
        "evidence_text": "query = f\"SELECT * FROM items WHERE name LIKE '%{q}%'\"",
        "reproduce_steps_text": "步骤",
        "verify_code_text": "python -B /src/verify/sql_injection.py",
    }
    value.update(overrides)
    return value


def test_general_plan_validation():
    plan = parse_general_plan(
        {
            "focus_areas": ["命令执行"],
            "file_globs": ["**/*.py"],
            "keywords": ["os.system"],
            "risk_hypotheses": ["命令注入"],
        }
    )
    assert plan["focus_areas"] == ["命令执行"]

    with pytest.raises(LLMValidationError):
        parse_general_plan({"focus_areas": []})


def test_code_findings_are_grounded_in_source():
    findings = parse_code_findings([_candidate()], FILES)
    assert len(findings) == 1
    assert findings[0].file_path == "app.py"
    assert findings[0].line_no == 2
    assert findings[0].verify_code_text == "python -B /src/verify/sql_injection.py"


def test_code_findings_reject_unknown_file_and_unsafe_command():
    findings = parse_code_findings(
        [
            _candidate(file_path="../outside.py"),
            _candidate(vuln_title="other", verify_code_text="sh -c rm -rf /"),
        ],
        FILES,
    )
    # 第一个路径非法；第二个证据可定位，但危险命令被丢弃为 None
    assert len(findings) == 1
    assert findings[0].verify_code_text is None


def test_report_output_filters_unverified_and_renumbers():
    paths, advice = parse_report_output(
        {
            "attack_paths": [
                {
                    "path_title": "路径",
                    "path_summary": "摘要",
                    "final_impact_text": "影响",
                    "items": [
                        {"vuln_code": "VULN-002", "step_order": 9, "step_text": "第二步"},
                        {"vuln_code": "VULN-001", "step_order": 3, "step_text": "第一步"},
                        {"vuln_code": "VULN-999", "step_order": 4, "step_text": "不存在"},
                    ],
                }
            ],
            "remediation": ["修复建议"],
        },
        {"VULN-001", "VULN-002"},
    )
    assert [item["vuln_code"] for item in paths[0]["items"]] == ["VULN-001", "VULN-002"]
    assert [item["step_order"] for item in paths[0]["items"]] == [1, 2]
    assert advice == ["修复建议"]


def test_verification_plan_rejects_unsafe_command():
    decisions = parse_verification_plan(
        [
            {
                "vuln_code": "VULN-001",
                "action": "execute",
                "verify_code_text": "python /etc/passwd.py",
                "reason": "bad",
            }
        ],
        {"VULN-001"},
    )
    assert decisions["VULN-001"].action == "skip"


def test_report_output_rejects_invalid_schema():
    with pytest.raises(LLMValidationError):
        parse_report_output({"attack_paths": "not-a-list"}, set())


def test_verification_prompt_includes_available_scripts():
    messages = verification_messages(
        [
            {
                "vuln_code": "VULN-001",
                "vuln_title": "SQL 注入",
                "file_path": "app.py",
                "verify_code_text": None,
            }
        ],
        ["/src/verify/sql_injection.py", "/src/verify/idor.py"],
    )
    text = messages[-1]["content"]
    assert "/src/verify/sql_injection.py" in text
    assert "/src/verify/idor.py" in text
    assert "优先 execute" in text


def test_verification_prompt_without_scripts_requests_skip():
    messages = verification_messages(
        [
            {
                "vuln_code": "VULN-001",
                "vuln_title": "SQL 注入",
                "file_path": "app.py",
                "verify_code_text": None,
            }
        ],
        [],
    )
    assert "没有可用的 /src/verify 脚本" in messages[-1]["content"]


def test_verification_retry_prompt_includes_failure_evidence():
    messages = verification_retry_messages(
        [
            {
                "vuln_code": "VULN-001",
                "vuln_title": "SQL 注入",
                "file_path": "app.py",
                "verify_code_text": "python -B /src/verify/sql_injection.py",
                "evidence_text": "退出码：1\n输出：missing table",
            }
        ],
        ["/src/verify/sql_injection.py", "/src/verify/idor.py"],
    )
    text = messages[-1]["content"]
    assert "失败证据" in text
    assert "missing table" in text
    assert "/src/verify/idor.py" in text
    assert "不同的验证脚本" in text
