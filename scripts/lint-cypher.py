#!/usr/bin/env python3
"""Cypher compatibility checker for Neo4j Community Edition.

Scans all Python service files for inline Cypher queries and flags
patterns incompatible with Neo4j 5 Community Edition.

Usage:
    python scripts/lint-cypher.py          # check all services
    python scripts/lint-cypher.py --ci     # exit with code 1 on violations

Known incompatible patterns (Neo4j 5 CE):
  1. x NOT IN [...]       → must use NOT x IN [...]
  2. EXISTS { subquery }   → scoped EXISTS not available in CE
  3. CALL { subquery }     → call subqueries limited in CE
  4. CREATE INDEX ... FOR  → must include IF NOT EXISTS
  5. CREATE CONSTRAINT ... → must include IF NOT EXISTS
  6. shortestPath in WHERE → CE doesn't support in WHERE clause
  7. EXPLAIN/PROFILE       → not for production queries
"""

import re
import sys
from pathlib import Path

SERVICES_DIR = Path(__file__).resolve().parent.parent / "services"

# Patterns that indicate a Cypher query string (triple-quoted or single-line)
QUERY_RE = re.compile(
    r'"""(.*?)"""'           # triple-quoted
    r'|'
    r"'''(.*?)'''"           # triple single-quoted
    r'|'
    r'"([^"]*(?:MATCH|CREATE|MERGE|RETURN|SET|DELETE|REMOVE|OPTIONAL|WITH|UNWIND|CALL|FOREACH)[^"]*)"',
    re.DOTALL | re.IGNORECASE,
)

# Cypher antipatterns for Neo4j Community Edition
RULES: list[tuple[str, re.Pattern[str], str]] = [
    (
        "NOT-IN-ORDER",
        re.compile(r'\b\w+\s+NOT\s+IN\s*\[', re.IGNORECASE),
        "Use `NOT x IN [...]` instead of `x NOT IN [...]`",
    ),
    (
        "SCOPED-EXISTS",
        re.compile(r'\bEXISTS\s*\{', re.IGNORECASE),
        "Scoped EXISTS { subquery } is not supported in Neo4j CE",
    ),
    (
        "CALL-SUBQUERY",
        re.compile(r'\bCALL\s*\{', re.IGNORECASE),
        "CALL { subquery } may not be available in Neo4j CE",
    ),
    (
        "MISSING-IF-NOT-EXISTS-INDEX",
        re.compile(
            r'CREATE\s+INDEX\s+(?!.*IF\s+NOT\s+EXISTS)',
            re.IGNORECASE,
        ),
        "CREATE INDEX should include IF NOT EXISTS for idempotent startup",
    ),
    (
        "MISSING-IF-NOT-EXISTS-CONSTRAINT",
        re.compile(
            r'CREATE\s+CONSTRAINT\s+(?!.*IF\s+NOT\s+EXISTS)',
            re.IGNORECASE,
        ),
        "CREATE CONSTRAINT should include IF NOT EXISTS for idempotent startup",
    ),
    (
        "EXPLAIN-PROFILE",
        re.compile(r'\b(EXPLAIN|PROFILE)\b', re.IGNORECASE),
        "EXPLAIN/PROFILE should not appear in production queries",
    ),
    (
        "COUNT-STAR-SUBQUERY",
        re.compile(r'COUNT\s*\{\s*', re.IGNORECASE),
        "COUNT { subquery } not available in all Neo4j CE versions",
    ),
    (
        "COLLECT-SUBQUERY",
        re.compile(r'COLLECT\s*\{\s*', re.IGNORECASE),
        "COLLECT { subquery } not available in all Neo4j CE versions",
    ),
]


class Violation:
    def __init__(self, file: str, line: int, rule: str, detail: str, snippet: str):
        self.file = file
        self.line = line
        self.rule = rule
        self.detail = detail
        self.snippet = snippet.strip()[:80]

    def __str__(self) -> str:
        return f"  {self.file}:{self.line}  [{self.rule}] {self.detail}\n    → {self.snippet}"


def extract_queries(filepath: Path) -> list[tuple[int, str]]:
    """Extract (line_number, query_text) pairs from a Python file."""
    text = filepath.read_text(encoding="utf-8")
    results = []

    for match in QUERY_RE.finditer(text):
        query = match.group(1) or match.group(2) or match.group(3)
        if not query:
            continue
        # Only keep strings that look like Cypher
        upper = query.upper()
        if not any(kw in upper for kw in ("MATCH", "CREATE", "MERGE", "RETURN", "SET ", "DELETE")):
            continue
        # Calculate line number
        line = text[:match.start()].count("\n") + 1
        results.append((line, query))

    return results


def check_query(filepath: str, line: int, query: str) -> list[Violation]:
    """Check a single Cypher query against all rules."""
    violations = []
    for rule_id, pattern, detail in RULES:
        if pattern.search(query):
            violations.append(Violation(filepath, line, rule_id, detail, query))
    return violations


def scan_services() -> list[Violation]:
    """Scan all Python files under services/ for Cypher violations."""
    all_violations: list[Violation] = []

    py_files = sorted(SERVICES_DIR.rglob("*.py"))
    scanned = 0

    for pyfile in py_files:
        # Skip __pycache__
        if "__pycache__" in str(pyfile):
            continue
        rel = pyfile.relative_to(SERVICES_DIR.parent)
        queries = extract_queries(pyfile)
        if queries:
            scanned += 1
        for line, query in queries:
            violations = check_query(str(rel), line, query)
            all_violations.extend(violations)

    print(f"Scanned {len(py_files)} Python files, {scanned} contained Cypher queries")
    return all_violations


def main() -> None:
    ci_mode = "--ci" in sys.argv

    violations = scan_services()

    if not violations:
        print("✓ No Cypher compatibility issues found")
        sys.exit(0)

    print(f"\n✗ {len(violations)} Cypher compatibility issue(s) found:\n")
    for v in violations:
        print(v)
        print()

    if ci_mode:
        sys.exit(1)


if __name__ == "__main__":
    main()
