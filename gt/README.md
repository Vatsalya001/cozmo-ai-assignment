# Ground truth: how every reference number is measured

The brief requires laser or tape ground truth on everything, with the raw measurements
submitted. Errors are only comparable if both sides measure the same thing the same way,
so the conventions below are fixed before any measuring starts, and the benchmark and the
head-to-head both use them.

## Conventions

Ground truth on this benchmark is taken with a **steel measuring tape**, which the brief
permits ("laser or tape ground truth on everything"). The conventions below are chosen so a
tape can realise them repeatably by one person.

| Quantity | Definition | Tape technique |
|---|---|---|
| **Wall length** | Inside face, corner to corner, at **skirting top** height | Lay the tape along the wall base, hooked into the corner |
| **Room diagonal** | Inside corner to opposite inside corner, **along the floor** | Floor diagonal equals the 1.2 m diagonal because walls are vertical; the floor is the only surface a tape can span unsupported |
| **Ceiling height** | Floor to ceiling, at **two points** per room, ≥ 1 m apart | Two-part: floor→table top, then table top→ceiling. Record both parts |
| **Opening width** | **Clear width**, inner jamb face to inner jamb face. Trim excluded | Across the opening at waist height |
| **Opening height** | Floor to the underside of the head jamb | Two-part if the tape buckles |
| **Damage extent** | Bounding box on the wall plane: width × height, plus height of its lower edge above the floor | Direct |
| **Footprint** | Sum of room floor areas, inside faces | Derived |

**Error** = |our value − measured value| for the same element measured the same way.

## Ground-truth uncertainty (must be stated in the report)

A tape is not a laser, and a benchmark that does not state the uncertainty of its own
reference is not a benchmark. Estimated one-sigma, from the repeat readings recorded in
`measurements.csv`:

| Quantity | Estimated sigma | Why |
|---|---|---|
| Wall length | ~3 mm | Tape sag and corner hooking |
| Diagonal | ~4 mm | Longer span, more sag |
| **Ceiling height** | **~6 mm** | Two-part measurement, two hooking errors added |
| Opening width | ~2 mm | Short, well-defined faces |

Consequence, stated plainly rather than hidden: G-CEIL asks for ≤ 1.5 cm, and our reference
for it carries ~6 mm of its own. A measured 1.4 cm error therefore cannot be called a pass
with confidence. Every gate result is reported alongside the reference uncertainty, and
"within the gate" is claimed only when the error clears it by more than the reference sigma.

## Why diagonals are mandatory

Wall lengths alone cannot detect a sheared plan: a room recovered as a parallelogram can
have four correct wall lengths and still be wrong. The diagonals pin the shape. Measure
both of them in every room that is even approximately rectangular.

## Procedure

1. Label every room on a paper sketch: `R1`, `R2`, … Label walls clockwise from the door:
   `R1.W1`, `R1.W2`, … Label openings `R1.O1`, … Keep the sketch; photograph it and commit it.
2. Measure everything in the table above with the laser measurer, bracing it flat against
   the wall face.
3. Take **each measurement twice**. If the two readings differ by more than 5 mm, take a third
   and record all of them.
4. Record every value in `gt/measurements.csv` (template: `gt/measurements_template.csv`)
   as you go, not afterwards from memory.
5. Photograph the laser display for the ceiling heights and the opening widths. Those are the
   two the gates are tightest on.

## Staged damage

Two classes, printed at a known physical size and taped to the wall of a furnished room.
Record the printed size and the position of the lower-left corner from two walls and the floor.
This gives exact ground truth for class, extent and position, and it is fully removable.
The method is disclosed in the technical report: staged means staged.
