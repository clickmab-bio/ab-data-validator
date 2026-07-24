from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _dockerignore_patterns() -> set[str]:
    return {
        line.strip()
        for line in (PROJECT_ROOT / ".dockerignore").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def test_dockerignore_excludes_local_build_artifacts():
    patterns = _dockerignore_patterns()

    assert {
        "docs/",
        ".worktrees/",
        "*.[xX][lL][sS]",
        "*.[xX][lL][sS][xXmMbB]",
        "*.[xX][lL][tT][xXmM]",
        "*.[xX][lL][aA][mM]",
    } <= patterns
