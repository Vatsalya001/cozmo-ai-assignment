# Capture steps for the bedroom and bathroom

Open **`capture_plan.png`** beside this page. Every letter and number below is marked on it.

- **Dark line** = a wall you measure. **Red line** = a doorway (a gap, not a wall).
- **Lettered circle (A, B, C, D)** = where to stand. **Numbered arrow** = one photo, pointing where to aim.
- Wall ids on the drawing match the `element` column of `measurements_to_fill.csv` exactly.

**The drawing carries no lengths and no scale bar, on purpose.** Your tape readings are the ground
truth that scores both magicplan and this pipeline. If you see magicplan's numbers first, your tape
stops being independent and the whole comparison is scoring magicplan against a copy of itself. So
the drawing tells you *which* wall, never *how long*.

---

## Before you start

Lights on. Blinds open. Internal doors fully open. Do not move furniture.
Camera → Formats → **Most Compatible**. **HDR off.** No zoom. Phone upright and level.

Make these two folders:

```
data/own/myflat/
  1-bedroom/
  2-bathroom/
```

The `1-` and `2-` prefixes are not cosmetic. Rooms are numbered by folder order, and `bathroom`
sorts before `bedroom` alphabetically — without the prefixes your bathroom would be compared
against magicplan's bedroom.

---

## Part 1 — Bedroom photos (8 shots, ~6 min)

**Stand at A — in the MAIN doorway**, the wide one hard against the corner. (The opening in the
long wall is the bathroom door — that is `O-bottom`, and you do *not* start there.)
Do not move your feet between these four.

| shot | aim |
|---|---|
| **1** | straight ahead, down the length of the room |
| **2** | swing about 35° — it must overlap shot 1 by roughly a third |
| **3** | swing 35° again, covering the cupboard end and beyond |
| **4** | back to centre, then swing the other way, covering `W-right` |

**Walk to B — mid-room, facing the cupboard front.**

| shot | aim |
|---|---|
| **5** | square at the **cupboard doors** (`W-topleft`). This is the room boundary we are measuring |

**Walk to C — to the right of the cupboard, looking along it.**

| shot | aim |
|---|---|
| **6** | along the cupboard's **end** (`W-notch`) and the far wall past it |

**Walk to D — inside, facing the bathroom door.**

| shot | aim |
|---|---|
| **7** | square at `O-bottom` (the bathroom door), centred |

**Walk to E — inside, facing the main doorway you came in by.**

| shot | aim |
|---|---|
| **8** | square at `O-right`, centred |

Save all 8 into `1-bedroom/`. Do not add more — only the first 8 are used.

---

## Part 2 — Bathroom photos (6 shots, ~3 min)

**Stand at A — in the doorway.**

| shot | aim |
|---|---|
| **1** | straight ahead |
| **2** | swing left about 35° |
| **3** | swing right about 35° |

**Walk to B — the corner diagonally opposite the door.**

| shot | aim |
|---|---|
| **4** | back at the wall the door is in |
| **5** | the remaining wall |

**Walk to C — inside, facing the doorway.**

| shot | aim |
|---|---|
| **6** | square at `O1` |

Save all 6 into `2-bathroom/`.

**Mirror and shower glass: never aim straight at them.** Come at an angle. Dry the floor if it is wet.

---

## Part 3 — Tape measurements (~30–40 min)

Fill `measurements_to_fill.csv`. **Two readings for every row.** If they differ by more than 5 mm,
take a third and put it in the `note` column.

**Do not open `magicplan_results.md` first.** That is the point of measuring blind.

### Bedroom — walk it clockwise from the main doorway

Stand in the **main doorway** facing in, then walk the perimeter keeping the wall on your left:

| order | row | has a door? | how to measure |
|---|---|---|---|
| 1 | `R1.W-bottom` | **yes** — the bathroom door | corner to corner, **straight through the opening** |
| 2 | `R1.W-left` | no | corner to corner |
| 3 | `R1.W-topleft` | no | the **cupboard front**, along its doors |
| 4 | `R1.W-notch` | no | the **cupboard end**, where it stops |
| 5 | `R1.W-topright` | no | from the cupboard end to the start of the main doorway |
| 6 | `R1.W-right` | no | corner to corner |

**The cupboard counts as wall.** It is built in and cannot be moved, magicplan modelled it as a
wall, and a floor plan describes usable space — so measuring to its face is the right call. Put
`cupboard face, built-in, treated as wall` in the `note` column for rows 3, 4 and 5. What matters
is that the convention is *recorded*: all three sources must be answering the same question.

Then:

- `R1.O-bottom` / `R1.O-right` — **clear width**, inner frame face to inner frame face, trim excluded.
  Each also has an **opening_height** row: floor to the underside of the frame.
- `R1.X1` / `R1.X2` — the two diagonals, inside corner to opposite inside corner, across the floor.
  **Name the two corners in the note.** On an L-shaped room this is the only way to tell them apart.
- `R1.C1a` + `R1.C1b` — ceiling height at one spot, in **two parts**: floor to chair seat, then chair
  seat to ceiling. **Record each part on its own row. Do not add them up.**
- `R1.C2a` + `R1.C2b` — a second ceiling spot, at least 1 m from the first.

### Bathroom — clockwise from the doorway

Stand in the doorway facing in:

| row | which wall |
|---|---|
| `R2.W1` | on your **left** |
| `R2.W2` | straight **ahead** |
| `R2.W3` | on your **right** |
| `R2.W4` | the wall the **door is in**, behind you — corner to corner through the opening |

**Write whichever convention you actually used into the `note` column.** It matters more that it is
recorded than that it matches this page: a perfectly measured wall filed on the wrong row scores as
an error, and a recorded convention can always be joined correctly afterwards.

Then `R2.X1` / `R2.X2` (diagonals, name the corners), `R2.C1a` + `R2.C1b` (ceiling in two parts),
and `R2.O1` width and height.

---

## Part 4 — optional, only if time allows

Install **Stray Scanner**, record 20 seconds, export it, and check whether `odometry.csv` and
`rgb.mp4` appear in the folder. If they do, walk both rooms with it for 2 minutes and hand that over
too — that unlocks a second tier. If it refuses to run without a LiDAR sensor, stop; that is a
hardware fact about the phone and is recorded as one.

---

## What to expect from the result

The **bathroom is the fair test** — it is rectangular, which is what the photo tier assumes.

The **bedroom will come back as its bounding box**, with the cupboard recess filled in, so its
floor area will overshoot. That is documented behaviour of the photo tier, not a bad capture: `scanplan/ingest/photos.py`
states it outright ("an L-shaped room comes back as its bounding box"). Do not try to photograph
around it. It is more useful as a failure we named in advance than as one discovered afterwards.
