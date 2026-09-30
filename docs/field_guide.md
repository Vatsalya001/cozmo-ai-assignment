# Field guide — what to do, step by step

Print this. Take it with you. Tick each box as you finish it.
Device: **iPhone 16 (base)**. Measuring tool: **steel tape**. Property: **your 1 RK**.

Total time: about **2 hours 15 minutes**.

## What your flat is for, and what it is not for

The brief asks for a multi-room capture of three or more rooms plus a connector. **Your 1 RK
does not have to provide that** — the three captures Cozmo supplied already do, at 7 to 9
rooms each with a hallway.

Your flat exists in this benchmark for the two things the supplied captures cannot give:

1. **Real tape ground truth.** Nobody can measure a flat they have never stood in. Every
   accuracy number we report for the video and photo tiers comes from your rooms.
2. **A furnished room with damage of two classes**, measured.

Plus the head-to-head against magicplan, which needs two rooms you can measure.

A 1 RK gives us a main room, a kitchen and a bathroom: **three spaces and two or three
doorways**. That is enough to test room separation, doorway detection and stitching. The
compliance matrix will state plainly that the large multi-room requirement is met by the
supplied captures and not by ours.

---

# PART A — Before you leave the desk (20 minutes)

## A1. Install magicplan

☐ Open the **App Store**.
☐ Tap the **search** icon (bottom right), type `magicplan`, tap **Search**.
☐ Tap **GET** next to "magicplan" (the icon is a blue/white floor-plan symbol).
☐ Wait for it to install, then **open it once** and let it ask for camera permission. Tap **Allow**.
☐ Create a free account if it asks. The free tier is enough.

## A2. Find magicplan's version number (you must record this)

The brief requires you to name the app **and its version**. Two ways:

**Way 1 — from the App Store (most reliable):**
1. Open the **App Store**.
2. Tap **search** (bottom right), type `magicplan`, tap **Search**.
3. Tap the **magicplan** result to open its page.
4. Scroll **down** past the screenshots until you see a section headed **"Version History"** —
   the version number is shown right there, e.g. `Version 2024.3.1`.
   (If you only see "What's New", the version is printed next to it.)

**Way 2 — from inside the app:**
1. Open **magicplan**.
2. Tap the **menu** (three lines or a gear icon, usually top-left or bottom-right).
3. Tap **Settings**, then scroll to the bottom and look for **About** or **Version**.

☐ **Write the version here:** `magicplan version 2026.38.0`

Do the same for any other app you use, and write it down. If you cannot find a version
number, screenshot the App Store page — that is acceptable evidence.

## A3. Set up the Camera app

☐ Open **Settings** → scroll down → **Camera**.
☐ Tap **Formats** → select **Most Compatible**.
  *(This saves photos as JPEG instead of HEIC, which is simpler for the pipeline to read.)*
☐ Go back to **Camera** → tap **Record Video** → select **1080p at 30 fps**.
☐ On the same screen, if you see a toggle called **HDR Video**, turn it **OFF**.
☐ Go back to **Camera** → make sure **Grid** is **ON**. It helps you hold the phone level.

## A4. Damage — NOT NEEDED, we have real damage

**Skip printing anything.** The flat already has a large area of genuine wall damage:
blistered and peeling paint with visible cracking and moisture staining down to the
skirting. That is stronger evidence than a printed picture, because it proves the detector
works on a real defect rather than on a photograph of one.

It is used as **damage class 1: `peeling_paint`**, and it is measured in B3 below.

One staged item is still added as class 2, so that the brief's word "staged" is satisfied
and at least one region has exactly known dimensions. That is the electrical tape.

## A5. Collect your kit

☐ Steel measuring tape
☐ Black electrical tape (insulation tape) — for the staged crack
☐ A **chair or stool** — you will stand on it for ceiling measurements
☐ Pen and several sheets of paper
☐ This printed guide
☐ Your iPhone, **charged above 80%**

---

# PART B — Set up the flat (25 minutes)

Your 1 RK. Treat **every enclosed space as a room**, however small — main room, kitchen,
bathroom, and any entry passage.

## B1. Prepare every space

☐ Turn on **every light**, including the kitchen and bathroom lights.
☐ Open all curtains and blinds.
☐ Open **every internal door fully**, pushed flat against the wall. Bathroom and kitchen
   doors included — a closed door hides a whole room.
☐ **Do not move or tidy furniture.** The assignment asks for a furnished room; clutter is
   part of the test, not a problem.
☐ Dry any wet or shiny floor, or write a note that it was shiny.
☐ **Clear a walking lane** around the edges if anything blocks it completely — you need to
   be able to point the camera at every wall.

## B2. Draw and label your sketch — DO NOT SKIP THIS

Everything later depends on this. Without labels you cannot tell which measurement belongs
to which wall, and the whole benchmark becomes unusable.

☐ On paper, draw a rough top-down plan. **Accuracy does not matter at all** — this is a
  naming diagram, not a drawing.
☐ Number each space. For a 1 RK that is typically:

```
R1 = main room
R2 = kitchen
R3 = bathroom
R4 = entry passage, if you have one
```

☐ In each space, start at its **doorway** and go **clockwise**. Label each wall:
  `R1.W1`, `R1.W2`, `R1.W3`, `R1.W4`.
☐ Label every doorway and opening: `R1.O1` = flat's main entrance, `R1.O2` = opening to the
  kitchen, and so on. **A doorway between two rooms gets one label**, written on both rooms.
☐ Draw an **arrow marking where you will start and finish your walk**.

Example, written out:

```
R1 (main room): W1 = wall with the bed, W2 = wall with the window,
                W3 = the damaged wall, W4 = wall with the entrance
                O1 = main entrance door, O2 = doorway to kitchen,
                O3 = doorway to bathroom
R2 (kitchen):   W1..W4 clockwise from O2
R3 (bathroom):  W1..W4 clockwise from O3
```

☐ **Photograph the sketch** with your phone. Keep the paper too.

## B3. Stage the damage

You need **two different kinds** of damage in **one furnished room**, on **two different walls**.
One is real and already there. One you add.

### Damage 1 — the real peeling paint (already exists)

This is the blistered, flaking wall area with the crack through it and the staining down at
the skirting. **Do not touch it or clean it.** Just measure it.

Its edges are fuzzy, so use this rule and use it consistently: **the bounding box of the
visibly blistered, flaking or discoloured area** — the smallest rectangle that contains all
of the damage.

☐ Hold the tape horizontally. Measure from the **leftmost** point of the damage to the
  **rightmost** point. That is the **width**.
☐ Hold the tape vertically. Measure from the **lowest** point to the **highest** point.
  That is the **height**.
☐ Measure from the **bottom edge of the damage** straight down to the **floor**.
☐ Measure from the **left edge of the damage** across to the **nearest side wall or door frame**.
☐ Take **3 photos** with the tape measure held against the damage so the numbers are readable:
  one showing the width, one the height, one the height above the floor.

### Damage 2 — the staged crack (you add this)

☐ On a **different wall of the same room**, use the black electrical tape to make a
  **jagged vertical line**, like a crack. About **90 cm long**, one tape-width wide (~2 cm).
  Don't make it straight — real cracks zigzag.
☐ Measure and write down: total **length**, **width**, height of its **bottom end above the
  floor**, and distance from its bottom end to the **nearest side wall**.
☐ Photograph it with the tape measure in shot.
☐ **Peel it off** when you have finished all the recording.

☐ **Write it down:**
```
Peeling paint (real):  room R__ , wall R__.W__ , size ____ x ____ cm,
                       bottom edge ____ cm above floor, left edge ____ cm from wall R__.W__

Crack (staged, tape):  room R__ , wall R__.W__ , size ____ x ____ cm,
                       bottom end ____ cm above floor, ____ cm from wall R__.W__
```

**Why one real and one staged:** the real defect is far better evidence that the detector
works on an actual defect rather than on a printout, and the staged one gives at least one
region whose true size is known exactly rather than judged by eye. The report states plainly
which is which.

---

# PART C — Record the walks (25 minutes)

## The one rule that matters in a small flat

Your phone works out 3D shape by seeing the same wall from **two different positions**.
Standing in the middle and spinning gives it almost nothing to work with.

So in every space: **keep moving sideways**, even if it is only a step or two. Slide along
each wall rather than pivoting on the spot. In a bathroom where you genuinely cannot walk,
step in and out and shift left and right — any sideways movement is better than none.

## C1. Video walk number 1

☐ Open the **Camera** app, swipe to **VIDEO** mode.
☐ Stand at your start point (the arrow on your sketch), just inside the main entrance.
☐ Hold the phone **upright** (portrait), at **chest height**, camera pointing at the **wall**.
☐ Press the **red record button**.
☐ **Stand completely still and count to 3.** Do not move yet.

**In the main room (R1):**
☐ Walk **slowly** around the room, about one step per second, staying as far from the wall
  you are filming as the furniture allows. **Half a metre is fine** if that is all you have.
☐ Keep the camera pointed at the wall, and keep **sliding sideways** as you go.
☐ Do one slow sweep: tilt down until you see the **floor** (count to 3), then up until you
  see the **ceiling** (count to 3), then back to level. **This is how ceiling height gets
  measured.**
☐ When you reach the damaged wall, **slow right down** and give it a few extra seconds from
  two or three different standing positions.

**In the kitchen (R2) and bathroom (R3):**
☐ **Pause 2 seconds in the doorway**, facing straight through it.
☐ Step inside. Even in a tiny space, **shuffle from one side to the other** while filming
  each wall. Two or three sideways steps is enough.
☐ Do the floor-and-ceiling sweep here too.
☐ Step back out through the doorway, again facing straight through it.

**Finishing:**
☐ **Never whip the phone around a corner.** Turn your whole body slowly.
☐ Return to your **exact starting point**, stand still, count to 3, press stop.
☐ The whole walk should be **60 to 90 seconds**. Under 2 minutes regardless.

☐ **Rename it later as:** `video_a.mov`

## C2. Video walk number 2

☐ Do **exactly the same walk again**, same route, same order, same pace.

This second walk is how the assignment measures whether your system gives the **same answer
twice**. Without it you lose that entire scoring row. It is not optional.

☐ **Rename it later as:** `video_b.mov`

## C3. Photographs

The brief allows **2 to 8 stills per room**. Do each space separately.

**Main room (R1) — 7 or 8 photos:**
☐ Stand in the **doorway**. Take **3 photos**: facing left, straight ahead, and right. Each
  should overlap the next by about a third.
☐ Move to one **corner**. Take **2 photos** covering the two opposite walls.
☐ Move to the **opposite corner**. Take **2 photos** covering the remaining walls.
☐ Take **1 photo squarely facing the damaged wall.**

**Kitchen (R2) — 4 to 6 photos:**
☐ From the **doorway**: 2 photos, left half and right half.
☐ Step inside and take 2 to 4 more covering every wall, moving sideways between shots.

**Bathroom (R3) — 3 or 4 photos:**
☐ From the **doorway**: 2 photos.
☐ Step in and take 1 or 2 more. If it is too small to step back in, shoot from the doorway
  at different heights and angles.

**For all of them:**
☐ Keep the phone **upright and level** — use the grid. **Never zoom.**
☐ **Never exceed 8 photos in one room.** The brief caps it.
☐ Photograph each space's shots **together, in a run**, so you can tell later which photo
  belongs to which room.

☐ On your sketch, **write how many photos you took in each space.**

---

# PART D — Measure everything (45 minutes)

This is the most valuable part of the whole exercise, and the most boring. Do it carefully:
these numbers are the only real ground truth in the entire submission, and they are the one
thing the supplied captures cannot provide.

A 1 RK is roughly **12 to 16 walls** in total, so this is quicker than it looks.

## D1. How to record

Open `gt/measurements_template.csv` on your computer afterwards, or write on paper now using
this layout. **Take every measurement twice.** If the two readings differ by more than half a
centimetre, take a third and write all three down.

```
room | element   | type          | reading 1 | reading 2 | note
R1   | R1.W1     | wall          | 3.412     | 3.414     | TV wall
R1   | R1.D1     | diagonal      | 4.286     | 4.288     | NE to SW
R1   | R1.C1     | ceiling       | 2.706     | 2.705     | near window
R1   | R1.O1     | opening_width | 0.812     | 0.813     | main door
```

## D2. Wall lengths

For **every wall in every room**:

☐ Hook the tape's metal end into one corner, **at floor level along the skirting**.
☐ Pull the tape along the base of the wall to the opposite corner.
☐ Read the number **where the wall ends**, not where the skirting board ends.
☐ Write it down. Measure again. Write that down too.

*Tip: if you're alone and the tape keeps falling, press the hooked end into the corner with
your foot.*

## D3. Room diagonals — both of them, in every room

☐ Stretch the tape across the floor from one corner to the **opposite** corner. Write it down.
☐ Do the **other** diagonal too (the other pair of opposite corners). Write it down.

**Why this matters:** if your system reports a room as a slightly squashed parallelogram
instead of a rectangle, all four wall lengths can still be correct. Only the diagonals
reveal it. Measure both in every room.

## D4. Ceiling heights — two per room

A tape bends if you extend it more than about 2 metres upward, so do it in **two parts**:

☐ Put the chair somewhere in the room. Measure from the **floor to the top of the chair seat**.
  Write it down (e.g. `0.452`).
☐ Stand on the chair. Measure from the **seat** straight up to the **ceiling**.
  Write it down (e.g. `2.254`).
☐ **Write both numbers separately.** Do not just add them up — I need both parts.
☐ Move the chair **at least 1 metre** away and do it again. That's your second point.

☐ Do this in **every room**.

## D5. Doorways

For **every doorway and opening**:

☐ Measure the **width** across the opening at about waist height, from the **inside face of
  one door frame to the inside face of the other**. Do not include the decorative trim.
☐ Measure the **height** from the floor to the **underside of the top of the frame**.
☐ Write both down, twice each.

## D6. Photograph your readings

☐ For every **ceiling height** and every **doorway width**, take a photo of the tape with the
  number visible. These two are the tightest accuracy targets in the assignment, so having
  photographic evidence is worth the extra minute.

---

# PART E — Head-to-head against magicplan (45 minutes)

**Do this before you leave the flat.** It is worth 10% of the entire score, and it is the
single thing the reference submission scored zero on — purely because they left it too late.

## E1. Choose your rooms

The brief asks for **2 rooms**. In a 1 RK that is almost certainly:

☐ **R1, the main room** — your largest and most rectangular space.
☐ **R2, the kitchen** — or the bathroom, whichever is more rectangular and less cluttered.

☐ **Write down which two you chose:** `______` and `______`

*If magicplan refuses to scan a space as small as your bathroom, use the kitchen. If it
struggles with both, scan the main room only and record plainly that the app could not
handle the second space — that is a real finding about the incumbent, and it belongs in the
head-to-head table rather than being quietly dropped.*

## E2. Scan them with magicplan

☐ Open **magicplan**. Start a new project.
☐ Follow **magicplan's own on-screen instructions exactly.** Do not try to use your own
  capture protocol here — you are testing the app fairly, at its best.
☐ Scan the **first** room. Let it finish and produce a room shape.
☐ Scan the **second** room the same way.

## E3. Write down what magicplan says

For **each** of the two rooms, find and write down:

☐ Room **width**
☐ Room **length**
☐ **Floor area**
☐ **Ceiling height** (if it gives one)
☐ Each **door width** (if it gives one)

```
magicplan, room R__ :  width ____ m, length ____ m, area ____ m2, ceiling ____ m
magicplan, room R__ :  width ____ m, length ____ m, area ____ m2, ceiling ____ m
```

## E4. Export magicplan's file

☐ In magicplan, find **Export** or **Share** (usually an upward-arrow icon).
☐ Export as **PDF** (and floor plan image if offered).
☐ Email it to yourself or save it to Files so you can get it onto your computer.

The assignment requires you to submit the app's own export, not just its numbers.

## E5. Re-measure those two rooms extra carefully

☐ Go back over your tape measurements for those two rooms and check them again.
  They now serve as the reference for both your own accuracy and this comparison,
  so they need to be your best work.

---

# PART F — Get everything onto the computer (15 minutes)

☐ Create this folder: `~/Desktop/cozmo-case-study/data/own/`

☐ Copy in, with **exactly these names**:

```
data/own/
    video_a.mov                     first walk
    video_b.mov                     second walk
    photos/
        main room/                  one folder per space, named as on your sketch
        kitchen/
        bathroom/
    magicplan/
        <the PDF and anything else magicplan exported>
    sketch.jpg                      photo of your labelled paper sketch
    damage/
        peeling_paint.jpg           the real damage, with the tape in shot
        peeling_paint_width.jpg
        peeling_paint_height.jpg
        crack.jpg                   the staged tape crack
    measurements.csv                your numbers, typed up
```

☐ Type your paper measurements into `measurements.csv` using the layout in **D1**.
  If typing them up is slow, photograph every page clearly and I will read them.

☐ Tell me you're done.

---

# Quick checklist

Tick these off before you consider yourself finished:

☑ magicplan version written down — `2026.38.0`
☐ Camera set to Most Compatible, 1080p/30, HDR off, grid on
☐ Labelled sketch drawn and photographed (R1 main room, R2 kitchen, R3 bathroom)
☐ Real peeling-paint damage measured and photographed with the tape in shot
☐ Staged tape crack added on a different wall, measured, photographed
☐ Video walk A recorded, 60–90 s, returned to exact start
☐ Video walk B recorded, same route
☐ Photos taken per space, **never more than 8 in one room**
☐ Every wall measured twice
☐ **Both diagonals** measured in every space
☐ **Two ceiling heights** per space, each written as its two separate parts
☐ Every doorway width and height measured twice
☐ magicplan scanned two rooms, numbers written down, export saved
☐ Tape crack peeled off
☐ Everything copied into `data/own/`
