# Ground truth: how every reference number is measured

The brief requires laser or tape ground truth on everything, with the raw measurements
submitted. Errors are only comparable if both sides measure the same thing the same way,
so the conventions below are fixed before any measuring starts, and the benchmark and the
head-to-head both use them.

## Conventions

| Quantity | Definition |
|---|---|
| **Wall length** | Inside face, corner to corner, measured at **1.2 m** above the floor |
| **Room diagonal** | Inside corner to opposite inside corner, at 1.2 m |
| **Ceiling height** | Floor to ceiling, measured at **two points** per room, at least 1 m apart |
| **Opening width** | **Clear width**, inner jamb face to inner jamb face. Trim and architrave excluded |
| **Opening height** | Floor to the underside of the head jamb |
| **Damage extent** | Bounding box on the wall plane: width × height, plus height of its lower edge above the floor |
| **Footprint** | Sum of room floor areas, inside faces |

**Error** = |our value − measured value| for the same element measured the same way.

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
