"""The rendered plan and the human-readable summary.

The brief requires a rendered plan alongside the JSON, and specifically a plan "a homeowner
would recognise". So this draws dimensions on the walls rather than producing a bare outline:
a floor plan whose numbers are only in a JSON file beside it is not a floor plan.
"""
from __future__ import annotations

import math
from pathlib import Path

PX_PER_M = 90
MARGIN_PX = 70
MIN_LABEL_M = 0.35          # do not clutter the drawing with sub-350 mm walls


def _bounds(doc: dict):
    xs, ys = [], []
    for room in doc["rooms"]:
        for x, y in room["polygon"]:
            xs.append(x); ys.append(y)
    if not xs:
        return 0.0, 0.0, 1.0, 1.0
    return min(xs), min(ys), max(xs), max(ys)


def plan_svg(doc: dict) -> str:
    x0, y0, x1, y1 = _bounds(doc)
    w = (x1 - x0) * PX_PER_M + 2 * MARGIN_PX
    h = (y1 - y0) * PX_PER_M + 2 * MARGIN_PX

    def P(x, y):
        # y is flipped: world +z runs away from the viewer, SVG +y runs down the page.
        return (MARGIN_PX + (x - x0) * PX_PER_M, MARGIN_PX + (y1 - y) * PX_PER_M)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}" '
           f'viewBox="0 0 {w:.0f} {h:.0f}">',
           '<rect width="100%" height="100%" fill="#ffffff"/>',
           '<g font-family="Helvetica,Arial,sans-serif">']

    for room in doc["rooms"]:
        pts = " ".join(f"{P(x, y)[0]:.1f},{P(x, y)[1]:.1f}" for x, y in room["polygon"])
        out.append(f'<polygon points="{pts}" fill="#f2f4f7" stroke="#111111" stroke-width="3" '
                   f'stroke-linejoin="round"/>')

    for room in doc["rooms"]:
        for wall in room["walls"]:
            L = wall["length_m"]["value"]
            if L < MIN_LABEL_M:
                continue
            (ax, ay), (bx, by) = wall["start"], wall["end"]
            (px1, py1), (px2, py2) = P(ax, ay), P(bx, by)
            mx, my = (px1 + px2) / 2, (py1 + py2) / 2
            ang = math.degrees(math.atan2(py2 - py1, px2 - px1))
            if ang > 90 or ang < -90:
                ang += 180
            out.append(f'<text x="{mx:.1f}" y="{my - 5:.1f}" font-size="12" fill="#1a56db" '
                       f'text-anchor="middle" transform="rotate({ang:.1f} {mx:.1f} {my:.1f})">'
                       f'{L:.2f}</text>')

        cx = sum(p[0] for p in room["polygon"]) / len(room["polygon"])
        cy = sum(p[1] for p in room["polygon"]) / len(room["polygon"])
        tx, ty = P(cx, cy)
        area = room["floor_area_m2"]["value"]
        ceil = room["ceiling_height_m"]
        out.append(f'<text x="{tx:.1f}" y="{ty:.1f}" font-size="15" font-weight="bold" '
                   f'text-anchor="middle" fill="#111111">{room["id"]}</text>')
        out.append(f'<text x="{tx:.1f}" y="{ty + 18:.1f}" font-size="12" text-anchor="middle" '
                   f'fill="#444444">{area:.2f} m²</text>')
        mark = "" if ceil.get("observed", True) else " (not seen)"
        out.append(f'<text x="{tx:.1f}" y="{ty + 34:.1f}" font-size="11" text-anchor="middle" '
                   f'fill="#777777">h {ceil["value"]:.2f} m{mark}</text>')

    for room in doc["rooms"]:
        for op in room["openings"]:
            pass    # openings are drawn from the plan level once wall assignment lands

    cap = doc["capture"]
    fp = doc["plan"]["footprint_m2"]
    out.append(f'<text x="{MARGIN_PX}" y="{h - 24:.0f}" font-size="12" fill="#111111">'
               f'{cap["id"]} · {cap["tier"]} tier · {len(doc["rooms"])} rooms · '
               f'{fp["value"]:.2f} m² [{fp["ci_low"]:.2f}, {fp["ci_high"]:.2f}]</text>')
    out.append(f'<text x="{MARGIN_PX}" y="{h - 8:.0f}" font-size="10" fill="#777777">'
               f'every dimension in metres; intervals are nominal 90%</text>')
    out += ['</g>', '</svg>']
    return "\n".join(out)


def summary_md(doc: dict) -> str:
    cap = doc["capture"]
    fp = doc["plan"]["footprint_m2"]
    lines = [f"# {cap['id']} — {cap['tier']} tier", "",
             f"{len(doc['rooms'])} rooms · footprint **{fp['value']:.2f} m²** "
             f"({fp['ci_low']:.2f} to {fp['ci_high']:.2f}) · {cap['runtime_s']} s", "",
             "Every value carries a nominal 90% interval. Values the sensor never saw are "
             "marked *not observed* and given deliberately wide ranges.", "",
             "| Room | Floor area (m²) | Ceiling height (m) | Walls (m) | Openings (m) |",
             "|---|---|---|---|---|"]

    for room in doc["rooms"]:
        a, c = room["floor_area_m2"], room["ceiling_height_m"]
        wl = " · ".join(f"{w['length_m']['value']:.2f}" for w in room["walls"]
                        if w["length_m"]["value"] >= MIN_LABEL_M)
        op = " · ".join(f"{o['width_m']['value']:.2f}" for o in room["openings"]) or "none found"
        mark = "" if c.get("observed", True) else " *(not seen)*"
        lines.append(f"| {room['id']} | {a['value']:.2f} ({a['ci_low']:.2f}–{a['ci_high']:.2f}) "
                     f"| {c['value']:.2f} ({c['ci_low']:.2f}–{c['ci_high']:.2f}){mark} "
                     f"| {wl} | {op} |")

    warn = doc["quality"]["warnings"]
    if warn:
        lines += ["", "## What to be careful of", ""]
        lines += [f"- **{w['severity']}** — {w['message']}" for w in warn]
    return "\n".join(lines) + "\n"


def write_all(doc: dict, out_dir) -> list[str]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "plan.svg").write_text(plan_svg(doc))
    (out_dir / "summary.md").write_text(summary_md(doc))
    return ["plan.svg", "summary.md"]
