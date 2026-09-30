"""Schema validation for every result the pipeline writes.

A-SCHEMA requires 100% of outputs to validate and every interval to satisfy
ci_low <= value <= ci_high. JSON Schema cannot express that ordering across sibling
properties, so it is checked here and both checks run before a result is written to disk.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "output.schema.json"


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _interval_problems(node, trail="$") -> list[str]:
    """Every measurement object anywhere in the document must be internally consistent."""
    problems = []
    if isinstance(node, dict):
        if {"value", "ci_low", "ci_high"} <= node.keys():
            v, lo, hi = node["value"], node["ci_low"], node["ci_high"]
            if not (lo <= v <= hi):
                problems.append(f"{trail}: ci_low <= value <= ci_high violated ({lo}, {v}, {hi})")
        for k, child in node.items():
            problems += _interval_problems(child, f"{trail}.{k}")
    elif isinstance(node, list):
        for i, child in enumerate(node):
            problems += _interval_problems(child, f"{trail}[{i}]")
    return problems


def _reference_problems(doc: dict) -> list[str]:
    """A-FLAG and A-SCOPE: every flag names a real rule, every scope item points at a real
    surface and a real reason."""
    problems = []
    surfaces = {w["surface_id"] for r in doc.get("rooms", []) for w in r.get("walls", [])
                if w.get("surface_id")}
    damage_ids = {d["id"] for d in doc.get("damage", [])}
    rule_ids = {f["rule_id"] for f in doc.get("concealed_flags", [])}
    for item in doc.get("scope", []):
        if surfaces and item["surface_id"] not in surfaces:
            problems.append(f"scope {item['id']}: unknown surface_id {item['surface_id']}")
        if item["because"] not in damage_ids | rule_ids:
            problems.append(f"scope {item['id']}: 'because' {item['because']} is not a damage or rule id")
    return problems


def validate(doc: dict, *, strict: bool = True) -> list[str]:
    """Return a list of problems. Empty means the document is good."""
    problems = [f"schema: {e.message} at {'.'.join(str(p) for p in e.absolute_path)}"
                for e in jsonschema.Draft7Validator(load_schema()).iter_errors(doc)]
    problems += _interval_problems(doc)
    if strict:
        problems += _reference_problems(doc)
    return problems


def validate_file(path) -> list[str]:
    return validate(json.loads(Path(path).read_text()))
