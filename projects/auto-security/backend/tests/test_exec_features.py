from app.sandbox.manager import SandboxManager
from app.schemas.project import ProjectCreate
from app.workers.code_analyst import MAX_SEARCH_KEYWORDS, build_search_keywords


def test_search_keywords_include_builtin_and_task_terms():
    keywords = build_search_keywords("重点检查 SQL 注入和 os.system 调用")
    assert "sql" in keywords
    assert "os.system" in keywords
    assert "subprocess" in keywords
    assert len(keywords) <= MAX_SEARCH_KEYWORDS
    assert len(keywords) == len(set(keywords))


def test_search_keywords_deduplicate_case_insensitively():
    keywords = build_search_keywords("SQL sql SQL")
    assert keywords.count("sql") == 1


def test_command_output_is_truncated_with_marker():
    output = SandboxManager._truncate(b"x" * 100_000, 8192)
    assert output.endswith("...[truncated]")
    assert len(output.encode("utf-8")) <= 8192 + len("...[truncated]")


def test_project_isolation_defaults_to_system_config():
    payload = ProjectCreate(
        project_name="demo",
        source_path="D:/pythoncode/auto/examples/vuln-demo",
        task_content="检查 SQL 注入",
    )
    assert payload.isolation_type is None
