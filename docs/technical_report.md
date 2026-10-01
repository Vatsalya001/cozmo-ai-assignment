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
roughly 10–50 s on a CPU-only laptop, is byte-for-byte deterministic, and needs no weights — so it
cannot fail at a live demo because a checkpoint did not cache.

The video and photo tiers **do** use one pretrained model, disclosed here and in the compliance
matrix: `depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf`. They have no choice. Scale is
mathematically unobservable from monocular images — a dollhouse and a room project identically —
so a *metric* model is required, not a relative one: relative depth would leave the plan correct
in shape and unknown in size, which is not a floor plan. It is an explicit install extra, so the
LiDAR tier's offline guarantee survives.

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
| c00a170fe1 | 5 | 5 | 1 mm | 14.91 → 15.11 m² |
| 1a8384c3f6 | 25 | 15 | 6 mm | 47.50 → 48.04 m² |
| c7d28f72c6 | 124 | 27 | 12 mm | 47.87 → 49.65 m² |

*(published as `drift_ablation` in `bench/results/gates.json` — this table used to be
transcribed by hand from a log line and had gone stale by the time anyone looked.)*

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
| **Device depth bias** | **−18.0 mm, MEASURED against FARO laser truth, corrected at ingest**; the **4.1 mm standard deviation** of the per-scan medians is what one correction cannot fit, and it is carried in the interval |
| Tier thinness | ×1.0 LiDAR, **×11 video and photo — measured**, not chosen: ×4.5 left the reference outside the interval on both captures; the factors actually needed were ×9.1 and ×4.1 |

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

Those eight medians are summarised two ways in `bench/results/depth_bias.json`, under names
chosen so they cannot be confused: a **range of 13.0 mm**, which is the honest headline that no
single correction fits every scan, and a **standard deviation of 4.10 mm**, which is what
survives the correction and therefore what the interval must carry. Only the range used to be
published, while the code constant was set from the deviation — so a reader checking the 4 mm
against the benchmark would have found 13 and reasonably concluded it was invented. It was
correct and unverifiable, which is most of the way to wrong. `tests/test_traceability.py` now
re-derives both constants, and the sign, from the committed measurement.

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

**A second attempt** — hierarchical splitting, the "next thing to try" above — was built,
measured, and **reverted**: an experiment over 36 configurations predicted 7-vs-7 rooms and
1.4%, and the shipped version gave 6-vs-7 and 6.2%. Cause: the same error again, a harness that
bypassed `pipeline.run`. The rule that follows is narrow and useful — **a configuration sweep
must call the same entry point the product calls** — and it was *still* being broken, by the
very script that produces the evidence behind the declaration. The clean-clone check found that
third instance; the harness now asserts itself against `scanplan run` and exits non-zero if
they diverge, because writing the rule down had already failed twice.

**Postscript: the gate later moved, and not because of any of this.** Applying the measured
depth-bias correction took G-REPEAT-ROOMS to 5-vs-5 (**met**) while G-REPEAT-FOOTPRINT went
0.7% → 3.2% (**not met**). Exactly one of the two still passes and the correction flipped which
— two gates that trade places under 18 mm of depth were never measuring independent properties.
That is a side effect, not a third fix, and claiming it as one would repeat the original error
of naming the right outcome and the wrong mechanism.

Full account: [`fix_loop.md`](fix_loop.md), §6 for the post-mortem, §9 for the reverted second
attempt, §10 for both of the above.

## 6. Validation

86 tests. The ones that matter assert **accuracy against geometry we constructed and therefore
cannot be wrong about** — the fixture writes a real Stray Scanner export, so the actual loader
is exercised, not a mock. It also writes depth **18 mm short, exactly as the device does**, so
the correction is exercised rather than bypassed.

| Quantity | Truth | Measured | Error |
|---|---|---|---|
| Ceiling height | 2.500 m | 2.497 m | **−3.3 mm** |
| Floor height | 0.000 m | +0.002 m | **+1.8 mm** |
| Floor area | 12.000 m² | 11.636 m² | **−3.03%** |
| Long dimension | 4.000 m | 3.940 m | −60 mm |
| Short dimension | 3.000 m | 2.880 m | −120 mm |
| Polygon | rectangle | 4 walls | — |

**The area figure got worse when the pipeline got better, and that is the point.** It previously
read **+0.05%**, which looked near-perfect and was two errors cancelling: a 12 mm *over*-
correction inflated every room by roughly the amount the coverage-based area under-reports.
Measured directly — same fixture, correction set to the old over-corrected value — the area
comes back **+1.17%** instead of −3.03%. So the true behaviour of the area estimator was always
about −3%, and the old headline number was hiding it behind a sensor error.

A number that is accurate because two mistakes offset is worth less than a number that is
honestly off by 3%, because the first stops being right the moment either mistake is fixed.
The −3.03% is the coverage under-report showing through with nothing left to cancel it, and it
is consistent with the design: area is floor that was *seen*, so it can only run short.

Damage detection is tested in both directions: a 40 × 30 cm patch lifted 25 mm is found with
extent correct to 12 cm; a wardrobe 40 cm off the wall, and 4 mm of noise, are not reported.
Three real undamaged flats produce zero regions.

Also pinned: intervals never collapse below the measured residual bias, log-scale intervals
never go negative, unobserved values stay flagged, output is deterministic, no committed result
carries a machine-specific path, the compliance matrix's gate table matches the benchmark, and
the CLI never prints a traceback — in front of examiners a stated failure is worth more than a
stack trace.

**Reproduction.** `bench/clean_clone_check.sh` clones the repo, installs from scratch, runs the
tests, regenerates the benchmarks and diffs committed against regenerated. It classifies every
result file rather than counting files it never recomputed: an earlier version reported "8
identical" when seven of those had merely been copied by the clone and compared with themselves,
which is a pass that cannot fail. It has caught three real defects — a bare `ModuleNotFoundError`
on the default install, wall-clock seconds embedded in a gate *result*, and the fix-loop harness
measuring an unshipped pipeline.

## 7. Known failure modes

1. **No ground truth for the captures the pipeline runs on.** This is now the largest gap.
   Nobody has stood in the supplied properties with a tape, so most accuracy gates read *not
   measured* — including the head-to-head, where magicplan's own output is deliberately **not**
   used as truth, because it is the opponent and scoring an opponent against itself is circular.
   One measurement escapes this and it is the one that mattered: the depth bias, per-pixel
   against FARO laser depth registered to the same frames.
2. **The video tier is 27–60% from the LiDAR reference** on the same walks, and failed outright
   on the third capture with a stated `no floor found`. Its intervals are widened ×11 and do
   contain the reference 2/2, which is the correct response to an error of that size rather
   than a fix for it. Inferred depth is not measured depth, and the gap is the number this tier
   exists to report.
3. **The photo tier does not stitch, by construction.** Two folders in, two disconnected groups
   out. With no camera poses nothing in the input says how rooms relate, and an L-shaped room
   returns as its bounding box. The output carries an error-severity warning saying so rather
   than laying out a plausible arrangement.
4. **Footprint repeatability is 3.2%, not met** — and its sibling gate passes. See §5's
   postscript: the pair is not two independent properties.
5. **Rooms under-split against reference** — 5 found where the reference says 9. The safer
   failure: a merged pair still reports a correct combined area; an invented room does not.
6. **Damage class is shape-derived.** A stain that has not lifted the plaster is geometrically
   invisible. Every region says `class_source: "shape"` with confidence ≤ 0.5, and detection has
   no verified true-positive rate because no real damaged capture was obtainable.
7. **Mirrors and glass are not detected.** Two geometric tests were built; neither separates a
   reflection from ordinary geometry — one fired on 19–30% of every capture, the other on
   10–13%. The flag is **disabled deliberately** and every run warns that mirrors are
   undetected, which is worth more than a detector that fires everywhere. Wet/glossy floor and
   low light *are* detected and warned about.
8. **Room area is under-reported by design** — about −3% on known geometry. Coverage-based area
   cannot exceed what was seen, so occluded floor is missing rather than estimated.

## 8. What I would do next, in order

1. **Get tape truth onto two rooms.** It converts a whole column of *not measured* into numbers
   and unblocks the head-to-head. Highest value per hour by a wide margin — everything else on
   this list improves a number that is already known.
2. **Find a single-storey ARKitScenes venue with its laser cloud** and close G-CEIL. That turns
   an unmeasured gate into a measured one, which is worth more than improving a measured one.
   The obstacle is identification, not method: the method is written and runs.
3. **Replace the global `door_max_m`** with a split that adapts to local room scale. Two
   parameter attempts have failed; §5 is clear that this is not a parameter problem.
4. **Pose estimation for the video tier**, so it works on a bare clip rather than needing a pose
   track. That is structure-from-motion, and it would need its own validation before any number
   it produced could be trusted.
