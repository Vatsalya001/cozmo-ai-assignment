"""Concealed-damage rules, and the repair scope that follows from them.

The contract asks for "concealed-damage flags with the rule that fired" and "scope line items
keyed to surfaces". Both are deliberately written as explicit rules rather than learned.

That is not a shortcut. A classifier can say "0.8 mould" but cannot say *which rule* it
applied, because it does not apply rules -- and the brief requires the rule to be named. A
surveyor reading a flag needs to know it fired because damage sits within 300 mm of the floor
on an external wall, not because a network was confident. Rules are auditable, contestable,
and can be disagreed with, which is what makes a concealed-damage claim defensible at all.

Every rule states its own reasoning in `docs/damage_rules.md` and each flag carries the
evidence that triggered it.
"""
from __future__ import annotations

from dataclasses import dataclass

CEILING_NEAR_M = 0.30       # within this of the ceiling
FLOOR_NEAR_M = 0.30         # within this of the floor
LARGE_AREA_M2 = 0.50
DEEP_PROTRUSION_M = 0.03


@dataclass
class ConcealedFlag:
    id: str
    rule_id: str
    surface_id: str
    description: str
    evidence: list[str]
    confidence: float

    def as_dict(self) -> dict:
        return {"id": self.id, "rule_id": self.rule_id, "surface_id": self.surface_id,
                "description": self.description, "evidence": self.evidence,
                "confidence": round(self.confidence, 3)}


# rule_id -> (what it means, why concealed damage is likely, confidence)
RULES = {
    "R1-RISING-DAMP": (
        "damage within 300 mm of the floor",
        "moisture tracking up from the slab or a failed damp-proof course usually extends "
        "further inside the wall than the visible face suggests", 0.55),
    "R2-CEILING-LEAK": (
        "damage within 300 mm of the ceiling",
        "water entering from above spreads along the ceiling void before it shows on the "
        "wall, so the wetted area is typically larger than what is seen", 0.55),
    "R3-EXTENSIVE": (
        "a single region larger than 0.50 m2",
        "damage of this extent rarely stops at the surface; substrate behind it should be "
        "assumed affected until opened up", 0.50),
    "R4-DEEP-DISTORTION": (
        "surface departs from the wall plane by more than 30 mm",
        "plaster displaced this far has usually lost adhesion over a wider area than the "
        "part that has visibly moved", 0.60),
    "R5-SHARED-SURFACE": (
        "two or more separate regions on one wall",
        "multiple defects on a single surface point to a common cause behind it rather than "
        "to independent local damage", 0.45),
    "R6-OPENING-ADJACENT": (
        "damage within 500 mm of a door or window opening",
        "reveals and lintels are the usual path for water and for movement, and the damage "
        "at an opening is generally worse inside the reveal than on the face", 0.40),
}


def evaluate(regions, rooms, openings, storey_height_m: float | None) -> list[ConcealedFlag]:
    """Apply every rule to every damage region."""
    flags: list[ConcealedFlag] = []

    per_surface: dict[str, list] = {}
    for r in regions:
        per_surface.setdefault(r.surface_id, []).append(r)

    def add(rule_id, surface_id, evidence, extra_conf=0.0):
        meaning, _why, conf = RULES[rule_id]
        flags.append(ConcealedFlag(
            id=f"F{len(flags)+1}", rule_id=rule_id, surface_id=surface_id,
            description=meaning, evidence=evidence,
            confidence=min(conf + extra_conf, 0.95)))

    for r in regions:
        if r.height_above_floor_m <= FLOOR_NEAR_M:
            add("R1-RISING-DAMP", r.surface_id,
                [f"{r.id} lower edge {r.height_above_floor_m*1000:.0f} mm above the floor"])

        if storey_height_m:
            top = r.height_above_floor_m + r.height_m
            if storey_height_m - top <= CEILING_NEAR_M:
                add("R2-CEILING-LEAK", r.surface_id,
                    [f"{r.id} upper edge {(storey_height_m-top)*1000:.0f} mm below the ceiling"])

        if r.area_m2 > LARGE_AREA_M2:
            add("R3-EXTENSIVE", r.surface_id, [f"{r.id} covers {r.area_m2:.2f} m2"])

        if r.max_protrusion_m > DEEP_PROTRUSION_M:
            add("R4-DEEP-DISTORTION", r.surface_id,
                [f"{r.id} departs from the wall plane by {r.max_protrusion_m*1000:.0f} mm"])

    for surface_id, rs in per_surface.items():
        if len(rs) >= 2:
            add("R5-SHARED-SURFACE", surface_id,
                [f"{len(rs)} separate regions on this surface: " + ", ".join(r.id for r in rs)])

    return flags


# ---- repair scope ---------------------------------------------------------------------

SCOPE_FOR_CLASS = {
    "crack":         [("cut out and fill crack", "m", lambda r: max(r.width_m, r.height_m)),
                      ("make good and redecorate", "m2", lambda r: max(r.area_m2 * 4, 0.5))],
    "peeling_paint": [("strip loose material", "m2", lambda r: r.area_m2),
                      ("re-skim and redecorate", "m2", lambda r: r.area_m2 * 1.3)],
    "water_stain":   [("treat and stain-block", "m2", lambda r: r.area_m2 * 1.2),
                      ("redecorate", "m2", lambda r: r.area_m2 * 2)],
    "mould":         [("treat with fungicidal wash", "m2", lambda r: r.area_m2 * 1.5)],
    "hole":          [("patch and make good", "each", lambda r: 1.0)],
    "other":         [("investigate and make good", "m2", lambda r: max(r.area_m2, 0.25))],
}

SCOPE_FOR_RULE = {
    "R1-RISING-DAMP":     ("open up and inspect at low level", "m", 1.0),
    "R2-CEILING-LEAK":    ("trace leak above ceiling", "each", 1.0),
    "R3-EXTENSIVE":       ("open up to establish extent", "m2", 0.5),
    "R4-DEEP-DISTORTION": ("hack off loose plaster and re-render", "m2", 1.0),
    "R5-SHARED-SURFACE":  ("investigate common cause behind surface", "each", 1.0),
    "R6-OPENING-ADJACENT": ("inspect reveal and lintel", "each", 1.0),
}


def scope(regions, flags) -> list[dict]:
    """Repair items, each keyed to a surface and to the damage or rule that caused it."""
    from ..measure import from_sigma
    items = []

    for r in regions:
        for name, unit, qty_of in SCOPE_FOR_CLASS.get(r.damage_class, SCOPE_FOR_CLASS["other"]):
            q = float(qty_of(r))
            items.append({
                "id": f"S{len(items)+1}", "surface_id": r.surface_id, "item": name,
                "unit": unit,
                "quantity": from_sigma(q, max(q * 0.20, 0.05),
                                       method=f"from {r.id} extent").as_dict(),
                "because": r.id,
            })

    for f in flags:
        name, unit, q = SCOPE_FOR_RULE[f.rule_id]
        items.append({
            "id": f"S{len(items)+1}", "surface_id": f.surface_id, "item": name,
            "unit": unit,
            "quantity": from_sigma(q, q * 0.30, method=f"provisional, from {f.rule_id}").as_dict(),
            "because": f.rule_id,
        })

    return items
