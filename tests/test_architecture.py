"""Enforce the dependency rule: source code dependencies only point inwards."""
import ast
import dataclasses
import enum
import inspect
import typing
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "folio"

# layer -> modules it must never import
FORBIDDEN = {
    "domain": ["folio.application", "folio.infrastructure", "folio.presentation",
               "folio.bootstrap", "PySide6", "sqlite3"],
    "application": ["folio.infrastructure", "folio.presentation", "folio.bootstrap",
                    "PySide6", "sqlite3"],
    "infrastructure": ["folio.presentation", "folio.bootstrap", "PySide6"],
    # The UI talks to use cases only; the enums and errors it needs are re-exported
    # by folio.application.types and folio.application.errors.
    "presentation": ["folio.domain", "folio.infrastructure", "folio.bootstrap", "sqlite3"],
}


def imports_of(path: Path) -> set[str]:
    parts = path.relative_to(PACKAGE.parent).with_suffix("").parts
    package = ".".join(parts[:-1])  # for __init__.py this is the package itself
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - node.level + 1]
                name = ".".join(base + ([node.module] if node.module else []))
            else:
                name = node.module
            found.add(name)
    return found


@pytest.mark.parametrize("layer", sorted(FORBIDDEN))
def test_layer_respects_dependency_rule(layer):
    violations = []
    for path in sorted((PACKAGE / layer).rglob("*.py")):
        for imported in imports_of(path):
            for banned in FORBIDDEN[layer]:
                if imported == banned or imported.startswith(banned + "."):
                    violations.append(f"{path.relative_to(PACKAGE)} imports {imported}")
    assert not violations, "\n".join(violations)


def test_demo_builds_through_use_cases_only():
    banned = [i for i in imports_of(PACKAGE / "demo.py")
              if i == "folio.domain" or i.startswith("folio.domain.")]
    assert not banned


# ---- what crosses the application boundary --------------------------------------

def domain_types_in(hint) -> set[str]:
    """Domain classes (entities, value objects) named in a type hint; enums are allowed."""
    found = set()
    if inspect.isclass(hint):
        if hint.__module__.startswith("folio.domain") and not issubclass(hint, enum.Enum) \
                and not issubclass(hint, Exception):
            found.add(hint.__qualname__)
        return found
    for arg in typing.get_args(hint):
        found |= domain_types_in(arg)
    return found


def service_classes():
    from folio.application.services import Services
    return [hint for hint in typing.get_type_hints(Services).values()
            if inspect.isclass(hint) and hint.__module__.startswith("folio.application")]


def test_use_cases_neither_take_nor_return_domain_entities():
    leaks = []
    for cls in service_classes():
        for name, method in inspect.getmembers(cls, inspect.isfunction):
            if name.startswith("_"):
                continue
            for arg, hint in typing.get_type_hints(method).items():
                for leaked in domain_types_in(hint):
                    leaks.append(f"{cls.__name__}.{name} {arg}: {leaked}")
    assert not leaks, "\n".join(leaks)


def test_response_models_hold_no_domain_entities():
    from folio.application import inputs, records
    leaks = []
    for module in (inputs, records):
        for name, cls in inspect.getmembers(module, dataclasses.is_dataclass):
            if cls.__module__ != module.__name__:
                continue
            for field, hint in typing.get_type_hints(cls).items():
                for leaked in domain_types_in(hint):
                    leaks.append(f"{module.__name__}.{name}.{field}: {leaked}")
    assert not leaks, "\n".join(leaks)
