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

### Which mode you get, and why it matters

magicplan has three capture modes. **Two of them need LiDAR, which your iPhone 16 does not
have:**

| Mode | Needs LiDAR? | Available to you |
|---|---|---|
| Auto-Scan (whole floor at once) | Yes | ❌ no |
| Manual-Scan → **Wall Mode** | Yes | ❌ no |
| Manual-Scan → **Corner Mode** | No, uses AR | ✅ **this one** |

**Corner Mode works by you pointing at each floor corner and tapping.** The app then joins
the corners into a room. It is slower and less accurate than the LiDAR modes — magicplan is
typically **±5 to 15 cm per wall** without LiDAR. That is the bar you are being compared
against, and it is a low one.

### Prepare

☐ Turn on **every light**. Lighting is the single biggest factor in AR accuracy.
☐ Open the bathroom door flat against the wall.
☐ Open **magicplan** (version `2026.38.0` — already recorded).

### Scan R1 — the main room

☐ Tap **+** to create a new project. Give it a name.
☐ Tap to **add a room**, then choose **Start Manual-Scan**.
☐ Choose the **room type** when asked (Living Room, Bedroom — whatever fits).
☐ **Calibrate**: the app asks you to move the phone around. Aim at the floor near your feet
  and **move the device in slow circles** until it recognises the floor.
  *If nothing happens, move to a brighter part of the room and keep circling.*
☐ **Switch to Corner Mode.** Manual-Scan **opens in Wall Mode by default**, which your phone
  cannot use. Tap the **"Wall Mode" button on the right-hand side** of the screen to switch.
  You are in Corner Mode when a **corner placement indicator** appears.
☐ **Stand in one spot** where you can see as many corners as possible, ideally the middle of
  the room. Staying put for the whole scan gives the most accurate shape.
☐ **Aim at the first floor corner.** A **green indicator** shows where the corner will land.
  It either snaps automatically or you **tap the screen** to place it.
☐ Work around the room's perimeter, corner by corner. **Your open-plan L-shape just means
  more corners** — place one at every change of direction, including around the kitchen.
  *A white grid appears to help you aim through furniture.*
☐ **Close the loop**: aim back at the very first corner you placed, or tap **Done**.
☐ **Set the ceiling height**: use the grid to move from the floor up to the ceiling, and
  **tap once** when it reaches the right height.
☐ **Add doors and windows**: aim at each opening; a **green highlight** appears when it
  detects one; **tap** to place it. If it won't detect one, you can add it manually.
☐ Tap **Exit AR**, then **Yes, I'm sure**. The floor plan is created automatically.

**If you misplace a corner:** use the **undo arrow in the top-right** to reset the last action.

### Scan R2 — the bathroom

☐ Same procedure. Bathrooms are tight, so stand in the doorway if you cannot get a view of
  all four corners from inside.
☐ If magicplan **cannot complete** the bathroom, **write down exactly what failed** and move
  on with R1 only. An app that cannot scan a bathroom is a genuine limitation of the
  incumbent and belongs in the head-to-head table. It is not a failure on your side.

### Record what it reports

☐ Open each finished room in magicplan and read off its dimensions:

```
magicplan 2026.38.0   (no LiDAR, Corner Mode)
R1  width ______ m   length ______ m   area ______ m2   ceiling ______ m   door ______ m
R2  width ______ m   length ______ m   area ______ m2   ceiling ______ m   door ______ m
```

### Export — and a warning

☐ Tap **Export** or **Share** (usually an upward-arrow icon) → choose **PDF**.
☐ Email it to yourself or save it to Files.

⚠️ **magicplan's free tier often gates PDF export behind credits or a subscription.** If it
asks you to pay, **do not pay.** Instead:

☐ **Screenshot** the finished floor plan showing its dimensions
☐ **Screenshot** each room's detail/measurement view
☐ Write down in your notes: *"magicplan free tier would not export a PDF without payment;
  screenshots used instead."*

That is an honest, documented substitution, and the paywall itself is a legitimate finding
about the incumbent's free tier — the brief says a free tier is sufficient, so if it is not,
that is worth reporting.

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
