# scanplan — technical report

Phone captures to dimensioned, stitched floor plans with calibrated intervals.
Cozmo AI case study, October 2026.

---

## 1. Architecture

Three front-ends, one core.

```
Stray Scanner  ─┐
video .mov     ─┼─→  CaptureIR  ─→  geometry  ─→  error model  ─→  contract
photo folders  ─┘                                                  result.json
                                                                   plan.svg
                                                                   summary.md
```

`CaptureIR` (`scanplan/ir.py`) holds posed frames, a gravity-aligned metric point cloud,
plane hypotheses, and — explicitly — a `ScaleEstimate` carrying a value, a sigma and a
**provenance**. Everything downstream sees only the IR.

That single decision is what makes three tiers affordable. The tiers differ almost entirely in
*how metric scale is recovered*: LiDAR measures it, video infers it from a model, photos infer
it with less to go on. Making scale a first-class field with a stated origin, rather than an
implicit assumption baked into each path, means the geometry, the error model, the exports and
the benchmarks are written once.

**The LiDAR tier uses no neural model at all.** The phone measures distance directly; the rest
is plane fitting, rasterisation, morphology, connected components and least squares. It runs in
6–53 s on a CPU-only laptop, is byte-for-byte deterministic, and needs no weights — so it
cannot fail at a live demo because a 3 GB checkpoint did not cache.

## 2. Geometry pipeline

1. **Fusion.** Back-project depth using per-frame intrinsics — `fx` varies up to 2.1% *within*
   one capture, so a single camera matrix is not good enough. Voxel-reduce at 2 cm, keeping the
   first point per voxel rather than the centroid: a centroid across a voxel straddling two
   surfaces invents geometry nobody measured.
2. **Floor and ceiling.** The cloud is gravity-aligned, so these are the two dominant peaks of
   a height histogram — far more robust than plane RANSAC, because a floor is the only surface
   in a home with thousands of points at one exact height across the whole footprint. The
   odometry origin is the camera's start pose, not the floor, so both are fitted, never assumed.
3. **Yaw alignment.** Rotate so the dominant wall direction runs along the grid axis. The angle
   comes from Hough-detected **wall lines**, not from the principal axis of the floor scatter —
   that finds the direction the property is *longest* in, which for an L-shaped flat is a
   diagonal across the L matching no wall at all. Measured effect: 0% → 64% of walls within 10°
   of axis-aligned.
4. **Floor area = what was measured.** Not what a flood fill can reach. The fill was tried
   first and came out **3× too large** on every capture: the wall mask always has holes —
   stretches never pointed at, glass, an open doorway — and a fill escaping through one claims
   the outdoors as floor. Coverage cannot invent area, so errors run *too little*, never
   *imagined*.
5. **Rooms.** Split at doorway-width necks: erode by half a doorway, treat surviving components
   as seeds, grow back under a watershed. An open-plan kitchen stays one room because nothing
   narrow separates it.
6. **Regularisation.** Snap edges to the dominant axes **only where the move is smaller than
   the measurement noise**. A wall genuinely at 37° stays at 37°. A plan that is regular
   because the code insisted is confidently wrong, which the brief penalises harder than being
   visibly rough.

## 3. Drift handling

Submaps of 8 s, loop closures from revisits, a **4-DoF** pose graph (x, z, yaw) solved by
damped least squares. Roll and pitch are left alone: gravity is measured directly by the IMU
and is not in doubt, so optimising them would only let the solver trade real error against
imaginary error.

Loop closures come from revisits — two moments far apart in the walk but close in space are
almost certainly the same place, and the distance between them is drift made visible.

| Capture | Loop closures | Submaps | Max correction | Footprint off → on |
|---|---|---|---|---|
| c00a170fe1 | 5 | 5 | 1 mm | 14.65 → 15.40 m² |
| 1a8384c3f6 | 25 | 15 | 6 mm | 48.06 → 47.63 m² |
| c7d28f72c6 | 124 | 27 | 12 mm | 48.43 → 48.78 m² |

**The honest reading: ARKit's poses barely drift on this data.** Corrections top out at 12 mm
over a 100 m walk. Drift is not where the error lives here, which is why the fix loop was not
aimed at it. The footprint still moves by more than the correction, because small pose changes
reshuffle which cells the room split assigns where — worth knowing before treating a footprint
delta as evidence of anything.

The estimate is computed identically with `apply=False`, so the ablation compares one pipeline
against itself rather than two different ones.

## 4. Error budget and calibration

No physical quantity leaves the pipeline as a bare float. Every one carries a nominal 90%
interval, and the validator enforces `ci_low ≤ value ≤ ci_high` before anything is written.

| Source | Treatment |
|---|---|
| Depth noise at the surface | 2.5 cm sigma on a wall length |
| Plane-fit residual | RMS / √n |
| **Device depth bias** | **−18.0 mm, MEASURED against FARO laser truth, corrected at ingest**; the 4 mm the per-scan spread leaves unexplained is carried in the interval |
| Tier thinness | ×1.0 LiDAR, **×11 video and photo — measured**, not chosen: ×4.5 left the reference outside the interval on both captures |

The bias allowance exists because of a caught mistake. The first ceiling-height sigma came out
at **0.1 mm** — the standard error of 250,000 points. Arithmetically correct, and confident
garbage: no phone measures to a tenth of a millimetre. Averaging removes noise; it does not
remove a systematic offset.

That offset is now **measured, not assumed**. The first attempt compared *storey heights*
against FARO truth — frame-independent, and it doubles the signal, since a sensor reading long
by *d* puts the floor *d* low and the ceiling *d* high. It returned NOT MEASURED: storey height
is a difference of two fitted surfaces and needs a venue with exactly one floor and one ceiling,
and ARKitScenes is overwhelmingly not that. Screening 319 trajectories put the median vertical
camera movement at 4.8 m, and the scans downloaded had clouds spanning 5 m with no dominant
floor layer — the strongest 5 cm band held 1.8% of points where a real floor holds 10–20%.

The fix was to stop inferring. The upsampling split publishes device depth and laser-derived
depth for the **same frames**, so the bias is a per-pixel subtraction with no floor to find and
no venue geometry to be wrong about — and it needs 50 MB per scan rather than a 1.9 GB point
cloud. Result: **−18.0 mm over 4.79 million pixels across 8 scans**, per-scan medians −14 to
−27 mm. The device reads short; the correction adds it back at ingest.

Two wrong answers were caught before that conclusion. Inferring the vertical axis from the data
picked Z for one scan and Y for another *in the same venue*; their storeys then disagreed by
790 mm while the **mean looked like a respectable −20 mm bias**. A plausible answer assembled
from wrong parts is the worst failure mode available, and the benchmark now refuses to produce
a number rather than average two of them.

## 5. The fix loop

**Gate chosen:** G-REPEAT-ROOMS — the same flat walked twice gave **3 rooms one time and 6 the
other**, while G-REPEAT-FOOTPRINT was *met* at 1.9%. Area repeats; its division into rooms does
not. That pairing is the diagnosis in one line.

**Declared** (commit `e44441b`, before any fix): the seed filter admits cores of 0.0064 m².
**Predicted:** 5 vs 5, gate met.
**Result** (commit `c002a66`): **4 vs 5, gate still not met.** Footprint improved to 0.8%.

**The declared root cause was factually wrong.** `max(min_cells // 4, 16)` with
`min_cells = 3000` is **750 cells = 0.30 m²**; the 16 never applies. The ablation confirms it —
varying that threshold 0.25→0.50 changes nothing. The real lever was the erosion width. The
declaration named the right function and the wrong mechanism inside it.

Three measurement bugs surfaced while testing, each producing a plausible wrong answer, each
caught only by checking one harness against another:

1. The ablation harness omitted drift correction, reporting "before" as 7 vs 7 where the
   benchmark measured 3 vs 6 on identical data.
2. **Patching module constants did nothing** — Python binds default arguments at definition, so
   `DOOR_MAX_M` silently ignored the patch while `MIN_SEED_AREA_M2`, read in the function body,
   did not. The measured "before" was half the fix already applied.
3. The declared before-state was therefore not the before state. Only after correcting it did
   the harness reproduce the benchmark exactly — which is the check that should have come first.

Full account: [`fix_loop.md`](fix_loop.md).

## 6. Validation

68 tests. The ones that matter assert **accuracy against geometry we constructed and therefore
cannot be wrong about** — the fixture writes a real Stray Scanner export, so the actual loader
is exercised, not a mock.

| Quantity | Truth | Measured | Error |
|---|---|---|---|
| Ceiling height | 2.500 m | 2.497 m | **−3 mm** |
| Floor area | 12.000 m² | 12.006 m² | **+0.05%** |
| Long dimension | 4.000 m | 3.960 m | −40 mm |
| Short dimension | 3.000 m | 2.930 m | −70 mm |
| Polygon | rectangle | 4 walls | — |

Damage detection is tested in both directions: a 40 × 30 cm patch lifted 25 mm is found with
extent correct to 12 cm; a wardrobe 40 cm off the wall, and 4 mm of noise, are not reported.
Three real undamaged flats produce zero regions.

Also pinned: intervals never collapse below the unmeasured bias, log-scale intervals never go
negative, unobserved values stay flagged, output is deterministic, and the CLI never prints a
traceback — in front of examiners a stated failure is worth more than a stack trace.

## 7. Known failure modes

1. **Two of three tiers are not built.** Video and photo detect correctly and then raise a
   stated error. This is the largest gap in the submission.
2. **Room splitting is not repeatable.** 4 vs 5 on two walks of one flat. `door_max_m` is one
   global number and rooms are not one size: wide enough to split a room from a hallway erases
   a bathroom. The next thing to try is a hierarchical split recording the width at which each
   component separates, giving each room its own scale.
3. **Rooms under-split against reference** — 5 found where the reference says 9. The safer
   failure: a merged pair still reports a correct combined area; an invented room does not.
4. **No ground truth for the captures the pipeline runs on.** Every absolute number comes from
   synthetic geometry or from repeatability. The depth bias is an assumption, not a measurement.
5. **Damage class is shape-derived.** A stain that has not lifted the plaster is geometrically
   invisible. Every region says `class_source: "shape"` with confidence ≤ 0.5.
6. **Mirrors, glass and low light are not handled** — no detection, no warning.
7. **Room area is under-reported by design.** Coverage-based area cannot exceed what was seen,
   so occluded floor is missing rather than estimated.

## 8. What I would do next, in order

1. Build the video tier — it is the largest missing scoring surface.
2. Get tape truth onto two rooms, which converts a column of *not measured* into numbers.
3. Hierarchical room splitting, to move G-REPEAT-ROOMS.
4. Re-attempt the laser calibration on single-level ARKitScenes scans.
