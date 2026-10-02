"""Draw the architecture as a flowchart, for a reader who will not open the source.

Every box names the module that does the work, so the diagram is a map into the code rather than
a picture of an idea. The content is taken from `docs/technical_report.md` sections 1 and 2 and
from the module layout itself; nothing here is invented for the drawing.

The shape the diagram has to carry is the design decision worth defending: **three front-ends,
one core.** The tiers differ almost only in how metric scale is recovered -- LiDAR measures it,
video and photos infer it from a model -- so geometry, error model, exports and benchmarks are
written once. That is why the three input boxes converge on CaptureIR and nothing downstream
knows which tier it came from.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
OUT_PNG = ROOT / "data" / "own" / "architecture.png"
OUT_PDF = ROOT / "data" / "own" / "architecture.pdf"

INK = "#22303f"
LIDAR = "#1f6f3f"
INFER = "#b06a1f"
CORE = "#2d5a8e"
OUT = "#6b3a7a"
GREY = "#8a949e"


def box(ax, x, y, w, h, title, sub, colour, fc="#ffffff", lw=2.0, fs=10.5, subfs=8.0):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.012,rounding_size=0.02",
                                fc=fc, ec=colour, lw=lw, zorder=3))
    ax.text(x + w / 2, y + h * (0.62 if sub else 0.5), title, ha="center", va="center",
            fontsize=fs, weight="bold", color=colour, zorder=4)
    if sub:
        ax.text(x + w / 2, y + h * 0.26, sub, ha="center", va="center", fontsize=subfs,
                color=GREY, family="monospace", zorder=4)


def arrow(ax, p, q, colour=INK, lw=1.8, style="-|>"):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle=style, mutation_scale=16, lw=lw,
                                 color=colour, shrinkA=2, shrinkB=2, zorder=2))


def main() -> int:
    fig, ax = plt.subplots(figsize=(15.5, 9.6))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")

    ax.text(0.5, 0.965, "scanplan — three front-ends, one core", ha="center",
            fontsize=16, weight="bold", color=INK)
    ax.text(0.5, 0.933,
            "The tiers differ almost only in HOW METRIC SCALE IS RECOVERED. "
            "Everything downstream sees one intermediate representation.",
            ha="center", fontsize=9.5, color=GREY)

    # ---- inputs -------------------------------------------------------------------------
    ax.text(0.085, 0.875, "CAPTURE", fontsize=8.5, weight="bold", color=GREY)
    box(ax, 0.02, 0.76, 0.17, 0.085, "LiDAR walk", "Stray Scanner export", LIDAR, "#f2f8f4")
    box(ax, 0.02, 0.645, 0.17, 0.085, "Video walk", "rgb.mp4 + odometry.csv", INFER, "#fdf6ec")
    box(ax, 0.02, 0.53, 0.17, 0.085, "Photos", "one folder per room", INFER, "#fdf6ec")

    ax.text(0.235, 0.875, "SCALE", fontsize=8.5, weight="bold", color=GREY)
    box(ax, 0.215, 0.76, 0.165, 0.085, "depth MEASURED", "18 mm bias corrected", LIDAR, "#f2f8f4",
        fs=9.5)
    box(ax, 0.215, 0.5875, 0.165, 0.1425, "depth INFERRED",
        "Depth-Anything-V2\nMetric-Indoor-Small", INFER, "#fdf6ec", fs=9.5, subfs=7.4)

    for y in (0.8025, 0.6875, 0.5725):
        arrow(ax, (0.19, y), (0.215, y))

    # ---- the IR -------------------------------------------------------------------------
    arrow(ax, (0.38, 0.8025), (0.425, 0.715), CORE)
    arrow(ax, (0.38, 0.659), (0.425, 0.668), CORE)

    ax.add_patch(FancyBboxPatch((0.425, 0.588), 0.16, 0.155,
                                boxstyle="round,pad=0.012,rounding_size=0.02",
                                fc="#eef3f9", ec=CORE, lw=2.6, zorder=3))
    ax.text(0.505, 0.712, "CaptureIR", ha="center", va="center", fontsize=13, weight="bold",
            color=CORE, zorder=4)
    ax.text(0.505, 0.683, "scanplan/ir.py", ha="center", va="center", fontsize=7.4,
            color=CORE, family="monospace", zorder=4)
    ax.text(0.505, 0.633, "posed frames · metric cloud\nplane hypotheses\nScaleEstimate + provenance",
            ha="center", va="center", fontsize=7.2, color=GREY, family="monospace", zorder=4)

    ax.text(0.615, 0.667, "one representation —\nnothing below knows\nwhich tier it came from",
            ha="left", va="center", fontsize=8, style="italic", color=CORE)

    # ---- geometry pipeline ---------------------------------------------------------------
    ax.text(0.40, 0.505, "GEOMETRY   scanplan/geometry/", fontsize=8.5, weight="bold", color=GREY)
    steps = [
        ("1  Fusion", "fusion.py\n2 cm voxel, first point", 0.02),
        ("2  Floor + ceiling", "planes.py\nheight histogram peaks", 0.175),
        ("3  Yaw align", "walls.py\nHough wall lines", 0.33),
        ("4  Floor area", "rooms.py\nmeasured coverage", 0.485),
        ("5  Rooms", "rooms.py\nerode · watershed", 0.64),
        ("6  Regularise", "regularize.py\nonly within noise", 0.795),
    ]
    for title, sub, x in steps:
        box(ax, x, 0.345, 0.145, 0.105, title, sub, CORE, "#ffffff", lw=1.6, fs=9.5, subfs=7.0)
    for x in (0.165, 0.32, 0.475, 0.63, 0.785):
        arrow(ax, (x, 0.3975), (x + 0.01, 0.3975), CORE, lw=1.5)
    arrow(ax, (0.462, 0.588), (0.0925, 0.472), CORE, lw=1.6)

    # ---- error model + contract ----------------------------------------------------------
    ax.text(0.02, 0.278, "ERROR MODEL   scanplan/measure.py", fontsize=8.5, weight="bold",
            color=GREY)
    box(ax, 0.02, 0.145, 0.30, 0.105, "90% interval on every measurement",
        "widened x1 LiDAR · x11 video and photo", INK, "#f6f7f9", lw=1.8, fs=10, subfs=7.4)
    arrow(ax, (0.0925, 0.345), (0.0925, 0.253), CORE, lw=1.5)

    box(ax, 0.37, 0.145, 0.17, 0.105, "schema validated",
        "scanplan/validate.py\nbefore anything is written", INK, "#f6f7f9", lw=1.8, fs=10,
        subfs=7.0)
    arrow(ax, (0.32, 0.1975), (0.37, 0.1975), INK, lw=1.6)

    ax.text(0.572, 0.278, "OUTPUT", fontsize=8.5, weight="bold",
            color=GREY)
    outs = [("result.json", 0.615), ("plan.svg", 0.715), ("summary.md", 0.815),
            ("report.pdf", 0.915)]
    for name, x in outs:
        box(ax, x - 0.047, 0.145, 0.094, 0.105, name, "", OUT, "#f7f0fa", lw=1.8, fs=9.0)
    arrow(ax, (0.54, 0.1975), (0.548, 0.1975), INK, lw=1.6)

    ax.text(0.5, 0.075, "scanplan run <capture>        the tier is detected from the input",
            ha="center", fontsize=10, weight="bold", color=INK, family="monospace")
    ax.text(0.5, 0.038,
            "LiDAR tier uses NO neural model: plane fitting, rasterisation, morphology, "
            "connected components, least squares.\n"
            "Deterministic and offline — it cannot fail at a demo because a checkpoint did not "
            "cache.",
            ha="center", fontsize=8.2, color=GREY)

    fig.savefig(OUT_PNG, dpi=180, bbox_inches="tight", facecolor="white")
    fig.savefig(OUT_PDF, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"wrote {OUT_PNG.relative_to(ROOT)}")
    print(f"wrote {OUT_PDF.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
