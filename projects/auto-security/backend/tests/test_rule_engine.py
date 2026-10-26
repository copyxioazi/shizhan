from pathlib import Path

from app.rule_engine import scan_files

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "examples" / "vuln-demo"


def test_demo_project_hits_five_categories():
    files = [
        (path.relative_to(DEMO).as_posix(), path.read_text(encoding="utf-8"))
        for path in sorted(DEMO.rglob("*"))
        if path.is_file() and path.suffix in {".py", ".md", ".txt"}
    ]
    findings = scan_files(files)
    categories = {finding.category for finding in findings}
    assert categories == {
        "sql_injection",
        "command_injection",
        "path_traversal",
        "idor",
        "hardcoded_secret",
    }
    assert len(findings) == 5


def test_rule_engine_is_deterministic():
    files = [
        (path.relative_to(DEMO).as_posix(), path.read_text(encoding="utf-8"))
        for path in sorted(DEMO.rglob("*"))
        if path.is_file() and path.suffix in {".py", ".md", ".txt"}
    ]
    first = [finding.as_dict() for finding in scan_files(files)]
    second = [finding.as_dict() for finding in scan_files(files)]
    assert first == second


def test_verify_scripts_are_python_allowlisted():
    for path in sorted((DEMO / "verify").glob("*.py")):
        content = path.read_text(encoding="utf-8")
        assert "/src" not in content or "sys.path.insert" in content
