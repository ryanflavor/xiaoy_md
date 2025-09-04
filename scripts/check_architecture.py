#!/usr/bin/env python3
"""Hexagonal Architecture Boundary Enforcer.

Prevents architecture violations at commit time.
"""

import ast
from pathlib import Path
import sys
from typing import ClassVar


class HexagonalValidator(ast.NodeVisitor):
    """AST visitor to validate hexagonal architecture boundaries."""

    LAYER_RULES: ClassVar[dict[str, dict[str, list[str]]]] = {
        "domain": {
            "forbidden_imports": ["adapters", "infrastructure", "api", "web"],
            "allowed_imports": [
                "domain",
                "typing",
                "dataclasses",
                "enum",
                "abc",
                "pydantic",
            ],
        },
        "application": {
            "forbidden_imports": ["adapters", "infrastructure", "api", "web"],
            "allowed_imports": ["domain", "application", "typing"],
        },
        "adapters": {
            "forbidden_imports": [],  # Adapters can import from anywhere
            "allowed_imports": [],  # No restrictions (empty list means allow all)
        },
    }

    def __init__(self, file_path: Path) -> None:
        """Initialize validator for a specific file.

        Args:
            file_path: Path to the Python file to validate

        """
        self.file_path = file_path
        self.violations: list[str] = []
        self.current_layer = self._detect_layer(file_path)

    def _detect_layer(self, path: Path) -> str:
        """Detect which hexagonal layer this file belongs to."""
        parts = path.parts
        if "domain" in parts:
            return "domain"
        if "application" in parts:
            return "application"
        if "adapters" in parts:
            return "adapters"
        return "unknown"

    def visit_Import(self, node: ast.Import) -> None:
        """Check import statements."""
        for alias in node.names:
            self._validate_import(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Check from...import statements."""
        if node.module:
            self._validate_import(node.module)
        self.generic_visit(node)

    def _validate_import(self, module_name: str) -> None:
        """Validate import against layer rules."""
        if not self.current_layer or self.current_layer == "unknown":
            return

        rules = self.LAYER_RULES.get(self.current_layer, {})
        if not isinstance(rules, dict):
            return
        forbidden: list[str] = rules.get("forbidden_imports", [])

        for forbidden_pattern in forbidden:
            if forbidden_pattern in module_name:
                self.violations.append(
                    f"Architecture violation in {self.file_path}:\n"
                    f"  Layer '{self.current_layer}' cannot import from '{module_name}'\n"
                    f"  Forbidden pattern: '{forbidden_pattern}'"
                )


def validate_architecture(src_path: str = "src") -> tuple[bool, list[str]]:
    """Validate all Python files in src directory."""
    violations = []
    src_dir = Path(src_path)

    if not src_dir.exists():
        return True, []  # No source directory yet

    for py_file in src_dir.rglob("*.py"):
        with py_file.open(encoding="utf-8") as f:
            try:
                tree = ast.parse(f.read())
                validator = HexagonalValidator(py_file)
                validator.visit(tree)
                violations.extend(validator.violations)
            except SyntaxError as e:
                violations.append(f"Syntax error in {py_file}: {e}")

    return len(violations) == 0, violations


def check_layer_structure() -> tuple[bool, list[str]]:
    """Check if the proper layer structure exists."""
    required_dirs = [
        Path("src/domain"),
        Path("src/application"),
        Path("src/adapters"),
    ]

    missing_dirs = [
        str(dir_path) for dir_path in required_dirs if not dir_path.exists()
    ]

    if missing_dirs:
        return False, [f"Missing required directory: {d}" for d in missing_dirs]

    return True, []


def validate_imports_direction() -> tuple[bool, list[str]]:
    """Validate that imports follow the dependency rule (inward only)."""
    violations = []

    # Check domain files don't import from outer layers
    domain_path = Path("src/domain")
    if domain_path.exists():
        for py_file in domain_path.rglob("*.py"):
            with py_file.open(encoding="utf-8") as f:
                content = f.read()
                if "from src.adapters" in content or "from src.application" in content:
                    violations.append(
                        f"Domain violation in {py_file}: "
                        "Domain cannot import from adapters or application"
                    )

    # Check application files don't import from adapters
    app_path = Path("src/application")
    if app_path.exists():
        for py_file in app_path.rglob("*.py"):
            with py_file.open(encoding="utf-8") as f:
                content = f.read()
                if "from src.adapters" in content:
                    violations.append(
                        f"Application violation in {py_file}: "
                        "Application cannot import from adapters"
                    )

    return len(violations) == 0, violations


def main() -> int:
    """Validate hexagonal architecture boundaries."""
    print("🔍 Validating Hexagonal Architecture...")
    print("-" * 50)

    all_valid = True
    all_violations = []

    # Check layer structure
    print("\n📁 Checking layer structure...")
    structure_valid, structure_issues = check_layer_structure()
    if structure_valid:
        print("   ✅ Layer structure is correct")
    else:
        print("   ❌ Layer structure issues found")
        all_violations.extend(structure_issues)
        all_valid = False

    # Validate architecture boundaries
    print("\n🔒 Checking architecture boundaries...")
    arch_valid, arch_violations = validate_architecture()
    if arch_valid:
        print("   ✅ No architecture violations found")
    else:
        print("   ❌ Architecture violations detected")
        all_violations.extend(arch_violations)
        all_valid = False

    # Validate import directions
    print("\n➡️  Checking import directions...")
    import_valid, import_violations = validate_imports_direction()
    if import_valid:
        print("   ✅ Import directions are correct")
    else:
        print("   ❌ Import direction violations found")
        all_violations.extend(import_violations)
        all_valid = False

    # Print summary
    print("\n" + "=" * 50)
    if all_valid:
        print("✅ Architecture validation PASSED")
        print("\nYour code follows hexagonal architecture principles!")
        return 0
    print("❌ Architecture validation FAILED")
    print(f"\nFound {len(all_violations)} violation(s):\n")
    for violation in all_violations:
        print(f"  • {violation}")
    print("\nPlease fix these violations to maintain architecture integrity.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
