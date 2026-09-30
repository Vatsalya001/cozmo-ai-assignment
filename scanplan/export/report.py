"""The one-page visual report.

Somebody has to read this without opening a JSON file. So the page carries the plan, the room
table with its ranges, the damage and scope, and — deliberately given real space rather than a
footnote — the warnings.

The warnings are the part that matters most. A plan with a number on every wall looks equally
authoritative whether the ceiling was measured or guessed, and the difference only exists if
something on the page says so.

Rendered with matplotlib so it needs no browser and no external binary: the walk-in test is a
cold run on a machine we do not control.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                                    # noqa: E402
from matplotlib.patches import Polygon as MplPolygon              # noqa: E402

INK = "#111111"
MUTED = "#6b7280"
DIM = "#1a56db"
FILL = "#f2f4f7"
WARN = "#b45309"


def _draw_plan(ax, doc):
    ax.set_aspect("equal")
    ax.axis("off")
    rooms = doc["rooms"]
    if not rooms:
        ax.text(0.5, 0.5, "no rooms recovered", ha="center", va="center",
                transform=ax.transAxes, color=MUTED)
        return

    for room in rooms:
        poly = room["polygon"]
        ax.add_patch(MplPolygon(poly, closed=True, facecolor=FILL, edgecolor=INK, linewidth=1.6))

    for room in rooms:
        for wall in room["walls"]:
            L = wall["length_m"]["value"]
            if L < 0.35:
                continue
            (ax1, ay1), (ax2, ay2) = wall["start"], wall["end"]
            ax.text((ax1 + ax2) / 2, (ay1 + ay2) / 2, f"{L:.2f}",
                    fontsize=5.5, color=DIM, ha="center", va="center")

        cx = sum(p[0] for p in room["polygon"]) / len(room["polygon"])
        cy = sum(p[1] for p in room["polygon"]) / len(room["polygon"])
        ceil = room["ceiling_height_m"]
        mark = "" if ceil.get("observed", True) else "*"
        ax.text(cx, cy, room["id"], fontsize=8, weight="bold", ha="center", va="center", color=INK)
        ax.text(cx, cy - 0.28, f"{room['floor_area_m2']['value']:.2f} m²",
                fontsize=6.5, ha="center", va="center", color=MUTED)
        ax.text(cx, cy - 0.52, f"h {ceil['value']:.2f}{mark}",
                fontsize=6, ha="center", va="center", color=MUTED)

    ax.autoscale_view()


def _table_text(doc) -> str:
    lines = [f"{'Room':<6}{'Area m²':>18}{'Ceiling m':>14}{'Walls':>8}{'Openings':>10}",
             "-" * 56]
    for room in doc["rooms"]:
        a = room["floor_area_m2"]
        c = room["ceiling_height_m"]
        mark = "" if c.get("observed", True) else " *"
        area = f"{a['value']:.2f} ({a['ci_low']:.2f}-{a['ci_high']:.2f})"
        ceiling = f"{c['value']:.2f}{mark}"
        lines.append(f"{room['id']:<6}{area:>18}{ceiling:>14}"
                     f"{len(room['walls']):>8}{len(room['openings']):>10}")
    return "\n".join(lines)


def write_pdf(doc: dict, out_dir) -> list[str]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(8.27, 11.69))          # A4 portrait
    cap, fp = doc["capture"], doc["plan"]["footprint_m2"]

    fig.text(0.06, 0.965, f"{cap['id']}", fontsize=17, weight="bold", color=INK)
    fig.text(0.06, 0.945,
             f"{cap['tier']} tier · {len(doc['rooms'])} rooms · "
             f"{fp['value']:.2f} m² [{fp['ci_low']:.2f}, {fp['ci_high']:.2f}] · "
             f"{cap.get('runtime_s', 0):.1f} s",
             fontsize=9, color=MUTED)
    fig.text(0.06, 0.928,
             "every value carries a nominal 90% interval · * means the sensor never saw it",
             fontsize=7.5, color=MUTED)

    ax = fig.add_axes([0.06, 0.50, 0.88, 0.41])
    _draw_plan(ax, doc)

    y = 0.465
    fig.text(0.06, y, "Rooms", fontsize=10, weight="bold", color=INK)
    fig.text(0.06, y - 0.02, _table_text(doc), fontsize=7, family="monospace",
             color=INK, va="top")

    y -= 0.045 + 0.016 * (len(doc["rooms"]) + 2)
    fig.text(0.06, y, f"Damage and scope", fontsize=10, weight="bold", color=INK)
    if doc["damage"]:
        rows = [f"{d['id']}  {d['surface_id']:<12} {d['class']:<14} "
                f"{d['width_m']['value']:.2f} × {d['height_m']['value']:.2f} m"
                for d in doc["damage"][:6]]
        rows.append(f"{len(doc['concealed_flags'])} concealed-damage flag(s), "
                    f"{len(doc['scope'])} scope item(s)")
    else:
        rows = ["no damage regions found",
                "class would be shape-derived; naming a defect needs appearance"]
    fig.text(0.06, y - 0.018, "\n".join(rows), fontsize=7, family="monospace",
             color=INK, va="top")

    y -= 0.03 + 0.014 * (len(rows) + 1)
    warnings = doc["quality"]["warnings"]
    fig.text(0.06, y, f"What to be careful of  ({len(warnings)})",
             fontsize=10, weight="bold", color=WARN)
    wrapped = []
    for w in warnings:
        text = f"[{w['severity']}] {w['message']}"
        while len(text) > 108:
            cut = text.rfind(" ", 0, 108)
            wrapped.append(text[:cut])
            text = "    " + text[cut + 1:]
        wrapped.append(text)
    fig.text(0.06, y - 0.018, "\n".join(wrapped[:26]), fontsize=6.4, color=INK, va="top")

    fig.text(0.06, 0.02,
             f"scanplan {cap.get('pipeline_version', '')} · schema {doc['schema_version']} · "
             f"drift correction {'on' if cap.get('drift_correction') else 'off'}",
             fontsize=6.5, color=MUTED)

    pdf = out_dir / "report.pdf"
    fig.savefig(pdf, format="pdf")
    png = out_dir / "report.png"
    fig.savefig(png, format="png", dpi=110)
    plt.close(fig)
    return ["report.pdf", "report.png"]
