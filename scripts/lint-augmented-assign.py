#!/usr/bin/env python3
"""Lint for module-level augmented assignment misuse in functions.

Detects functions that use augmented assignment operators (+=, -=, *=, etc.)
on names that are neither local nor declared with `global` or `nonlocal`.
This is the recurring Python scoping bug pattern that causes
UnboundLocalError at runtime.

Usage:
    python scripts/lint-augmented-assign.py          # check all services
    python scripts/lint-augmented-assign.py --ci     # exit with code 1 on violations
"""

import ast
import sys
from pathlib import Path

SERVICES_DIR = Path(__file__).resolve().parent.parent / "services"

AUG_OPS = {
    ast.Add: "+=",
    ast.Sub: "-=",
    ast.Mult: "*=",
    ast.Div: "/=",
    ast.FloorDiv: "//=",
    ast.Mod: "%=",
    ast.Pow: "**=",
    ast.BitOr: "|=",
    ast.BitAnd: "&=",
    ast.BitXor: "^=",
}


class Violation:
    def __init__(self, file: str, line: int, name: str, op: str):
        self.file = file
        self.line = line
        self.name = name
        self.op = op

    def __str__(self) -> str:
        return (
            f"  {self.file}:{self.line}  "
            f"'{self.name} {self.op} ...' without global/nonlocal declaration"
        )


def _get_global_nonlocal_names(func_body: list[ast.stmt]) -> set[str]:
    """Collect names declared as global or nonlocal in a function body."""
    names: set[str] = set()
    for node in func_body:
        if isinstance(node, ast.Global):
            names.update(node.names)
        elif isinstance(node, ast.Nonlocal):
            names.update(node.names)
    return names


def _get_local_names(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Collect names that are clearly locally assigned before augmented use."""
    names: set[str] = set()
    # Function arguments
    for arg in func_node.args.args:
        names.add(arg.arg)
    for arg in func_node.args.posonlyargs:
        names.add(arg.arg)
    for arg in func_node.args.kwonlyargs:
        names.add(arg.arg)
    if func_node.args.vararg:
        names.add(func_node.args.vararg.arg)
    if func_node.args.kwarg:
        names.add(func_node.args.kwarg.arg)

    # Direct assignments (Name = ...) before augmented assignments
    for node in ast.walk(func_node):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.For):
            if isinstance(node.target, ast.Name):
                names.add(node.target.id)
            elif isinstance(node.target, ast.Tuple):
                for elt in node.target.elts:
                    if isinstance(elt, ast.Name):
                        names.add(elt.id)
        elif isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars and isinstance(item.optional_vars, ast.Name):
                    names.add(item.optional_vars.id)
    return names


def check_file(filepath: Path) -> list[Violation]:
    """Check a single Python file for augmented assignment issues."""
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8"), filename=str(filepath))
    except SyntaxError:
        return []

    rel = filepath.relative_to(SERVICES_DIR.parent)
    violations: list[Violation] = []

    # Collect module-level names (potential globals)
    module_names: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    module_names.add(target.id)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            module_names.add(node.target.id)

    # Walk functions
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        declared = _get_global_nonlocal_names(node.body)
        locals_ = _get_local_names(node)

        for child in ast.walk(node):
            if not isinstance(child, ast.AugAssign):
                continue
            if not isinstance(child.target, ast.Name):
                continue

            name = child.target.id
            op_str = AUG_OPS.get(type(child.op), "?=")

            # Flag if name is a module-level variable used without global/nonlocal
            # and is not a clearly local variable
            if name in module_names and name not in declared and name not in locals_:
                violations.append(Violation(str(rel), child.lineno, name, op_str))

    return violations


def scan_services() -> list[Violation]:
    """Scan all Python files under services/ for augmented assignment issues."""
    all_violations: list[Violation] = []
    py_files = sorted(SERVICES_DIR.rglob("*.py"))

    scanned = 0
    for pyfile in py_files:
        if "__pycache__" in str(pyfile):
            continue
        viols = check_file(pyfile)
        if viols:
            scanned += 1
        all_violations.extend(viols)

    print(f"Scanned {len(py_files)} Python files, {scanned} had potential issues")
    return all_violations


def main() -> None:
    ci_mode = "--ci" in sys.argv

    violations = scan_services()

    if not violations:
        print("✓ No augmented assignment scoping issues found")
        sys.exit(0)

    print(f"\n✗ {len(violations)} potential scoping issue(s) found:\n")
    for v in violations:
        print(v)
    print()

    if ci_mode:
        sys.exit(1)


if __name__ == "__main__":
    main()
