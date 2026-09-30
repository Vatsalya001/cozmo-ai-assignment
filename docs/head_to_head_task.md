# The only fieldwork left — 45 minutes

The benchmark runs on public data with FARO laser ground truth plus the three supplied
captures. This is the one piece that cannot come from a dataset: the brief requires running
a consumer scanning app on rooms **you can measure**, and submitting the app's own export.

Worth **10% of the total score**. It is the single item the reference submission left blank.

Two rooms: **R1** your main room (including the open kitchen area), **R2** your bathroom.

---

## Step 1 — Camera setup (2 minutes)

☐ Settings → Camera → **Formats** → **Most Compatible**
☐ Settings → Camera → **Record Video** → **1080p at 30 fps**
☐ Turn **HDR Video** off if the toggle is there
☐ Settings → Camera → **Grid** on

## Step 2 — Scan both rooms with magicplan (20 minutes)

☐ Turn on every light. Open the bathroom door flat against the wall.
☐ Open **magicplan** (version `2026.38.0` — already recorded).
☐ Scan **R1**, following **magicplan's own on-screen instructions**, not mine. You are
  testing the app fairly, at its best. If it offers a tutorial, follow it.
☐ Scan **R2** the same way.
☐ If magicplan refuses to scan a space as small as the bathroom, **write that down** and
  scan R1 only. An app that cannot handle a bathroom is a genuine finding about the
  incumbent and belongs in the table — it is not a failure on your side.

☐ **Write down what magicplan reports, for each room:**

```
magicplan 2026.38.0
R1  width ______ m   length ______ m   area ______ m2   ceiling ______ m   door ______ m
R2  width ______ m   length ______ m   area ______ m2   ceiling ______ m   door ______ m
```

☐ Export from magicplan: tap **Export** or **Share** (usually an upward arrow) → **PDF**.
  Email it to yourself or save to Files. **The export file must be submitted.**

## Step 3 — Tape-measure the same two rooms (20 minutes)

About 15 numbers in total. **Take every reading twice.** If two readings differ by more than
5 mm, take a third and write all of them down.

### Label first (2 minutes)

☐ On paper, sketch both rooms roughly. Number the walls **clockwise from each room's
  doorway**: `R1.W1`, `R1.W2`, … and `R2.W1` … `R2.W4`.
☐ Photograph the sketch.

### R1 — main room

☐ **Every wall length** — tape along the wall base, hooked into the corner, read where the
  wall ends (not where the skirting ends). An open-plan room may have 5 or 6 walls; do all.
☐ **Two cross-measurements** — corner to corner across the floor. An L-shaped room has no
  simple diagonals, so **write down which two corners each one runs between**:
  `from the W1/W2 corner to the W4/W5 corner`. A length without its endpoints is useless.
☐ **Ceiling height** — tape bends above 2 m, so do it in two parts: floor → chair seat,
  then chair seat → ceiling. **Record both parts separately**, do not just add them.
☐ **Main entrance door** — clear width, inner frame face to inner frame face, trim excluded.

### R2 — bathroom

☐ **Every wall length** (usually 4)
☐ **Both diagonals** — it is rectangular, so corner to opposite corner, twice
☐ **Ceiling height** — same two-part method
☐ **Doorway** — clear width, inner frame to inner frame

## Step 4 — Send it to the computer (3 minutes)

☐ Create `~/Desktop/cozmo-case-study/data/own/`
☐ Copy in:

```
data/own/
    magicplan/          the PDF and anything else it exported
    sketch.jpg          photo of your labelled sketch
    measurements.csv    your numbers, or clear photos of the paper
```

☐ Type the numbers in this layout, or just photograph the pages clearly and I will read them:

```
room,element,type,reading1,reading2,note
R1,R1.W1,wall,3.412,3.414,entrance wall
R1,R1.X1,cross,5.106,5.108,W1/W2 corner to W4/W5 corner
R1,R1.C1a,ceiling_part1,0.452,0.452,floor to chair seat
R1,R1.C1b,ceiling_part2,2.254,2.255,chair seat to ceiling
R1,R1.O1,opening_width,0.812,0.813,main entrance clear width
R2,R2.W1,wall,1.520,1.521,bathroom
R2,R2.D1,diagonal,2.410,2.412,corner to corner
```

---

## Checklist

☐ Camera app configured
☐ magicplan scanned R1 (and R2, or noted that it could not)
☐ magicplan's numbers written down for each room
☐ magicplan export saved (PDF)
☐ Sketch drawn, walls labelled, photographed
☐ R1: every wall, two named cross-measurements, ceiling in two parts, entrance width
☐ R2: every wall, both diagonals, ceiling in two parts, doorway width
☐ Everything copied into `data/own/`

That is the whole remaining fieldwork.
