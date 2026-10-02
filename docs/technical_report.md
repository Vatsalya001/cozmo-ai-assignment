# scanplan — technical report

Phone captures to dimensioned, stitched floor plans with calibrated intervals. Cozmo AI case
study, October 2026. Six pages by the brief's cap; the evidence chains are in the uncapped
documents this links to.

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

`CaptureIR` (`scanplan/ir.py`) holds posed frames, a gravity-aligned metric point cloud, plane
hypotheses, and — explicitly — a `ScaleEstimate` carrying a value, a sigma and a **provenance**.
Everything downstream sees only the IR, and that is what makes three tiers affordable: they
differ almost only in *how metric scale is recovered* — LiDAR measures it, video infers it from
a model, photos infer it with less — so geometry, error model, exports and benchmarks are
written once.

**The LiDAR tier uses no neural model at all.** The phone measures distance directly; the rest is
plane fitting, rasterisation, morphology, connected components and least squares. 10–50 s
on a CPU-only laptop, byte-for-byte deterministic, no weights — so it cannot fail at a demo
because a checkpoint did not cache.

The video and photo tiers **do** use one pretrained model, disclosed here and in the compliance
matrix: `depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf`. They have no choice. Scale is
mathematically unobservable from monocular images — a dollhouse and a room project identically —
so a *metric* model is required, not a relative one, which would leave the plan correct in shape
and unknown in size. It is an explicit install extra, so the LiDAR tier's offline guarantee
survives.

## 2. Geometry pipeline

1. **Fusion.** Back-project depth using per-frame intrinsics — `fx` varies up to 2.1% *within*
   one capture, so one camera matrix is not good enough. Voxel-reduce at 2 cm keeping the first
   point per voxel, not the centroid: a centroid across a voxel straddling two surfaces invents
   geometry nobody measured.
2. **Floor and ceiling** are the two dominant peaks of a height histogram on the gravity-aligned
   cloud — more robust than plane RANSAC, because a floor is the only surface in a home with
   thousands of points at one height across the whole footprint. The odometry origin is the
   camera's start pose, so both are fitted, never assumed.
3. **Yaw alignment** from Hough-detected **wall lines**, not the principal axis of the floor
   scatter — that finds the direction the property is *longest* in, a diagonal matching no wall
   in an L-shaped flat. Measured: 0% → 64% of walls within 10° of axis-aligned.
4. **Floor area = what was measured**, not what a flood fill can reach. The fill was tried first
   and came out **3× too large** on every capture: the wall mask always has holes — stretches
   never pointed at, glass, an open doorway — and a fill escaping one claims the outdoors as
   floor. Coverage cannot invent area, so errors run *too little*, never *imagined*.
5. **Rooms** split at doorway-width necks: erode by half a doorway, treat survivors as seeds,
   grow back under a watershed. An open-plan kitchen stays one room, nothing narrow separating it.
6. **Regularisation** snaps edges to the dominant axes **only where the move is smaller than the
   measurement noise**. A wall genuinely at 37° stays at 37°. A plan that is regular because the
   code insisted is confidently wrong, which the brief penalises harder than looking rough.

## 3. Drift handling

Submaps of 8 s, a **4-DoF** pose graph (x, z, yaw) by damped least squares, loop closures from
revisits — two moments far apart in the walk but close in space are almost certainly the same
place, and the distance between them is drift made visible. Roll and pitch are left alone:
gravity is measured by the IMU and is not in doubt, so optimising it would only let the solver
trade real error against imaginary error.

| Capture | Loop closures | Submaps | Max correction | Footprint off → on |
|---|---|---|---|---|
| c00a170fe1 | 5 | 5 | 1 mm | 14.91 → 15.11 m² |
| 1a8384c3f6 | 25 | 15 | 6 mm | 47.50 → 48.04 m² |
| c7d28f72c6 | 124 | 27 | 12 mm | 47.87 → 49.65 m² |

**The honest reading: ARKit's poses barely drift on this data.** Corrections top out at 12 mm
over a 100 m walk, so drift is not where the error lives — which is why the fix loop was not
aimed at it. The footprint still moves by more than the correction, because small pose changes
reshuffle which cells the room split assigns where: worth knowing before reading a footprint
delta as evidence of anything. The estimate is computed identically with `apply=False`, so the
ablation compares one pipeline against itself. Published as `drift_ablation` in `gates.json` —
this table used to be transcribed by hand and had gone stale.

## 4. Error budget and calibration

No physical quantity leaves the pipeline as a bare float. Every one carries a nominal 90%
interval, and the validator enforces `ci_low ≤ value ≤ ci_high` before anything is written.
Depth noise at the surface contributes a 2.5 cm sigma on a wall length, the plane-fit residual
RMS / √n. Two terms are larger, and both are measured:

- **Device depth bias: −18.0 mm**, against FARO laser truth, corrected at ingest. The **4.1 mm
  standard deviation** of the per-scan medians is what one correction cannot fit, and it is
  carried in the interval.
- **Tier thinness: ×1.0 LiDAR, ×11 video and photo — measured**, not chosen. ×4.5 left the
  reference outside the interval on both captures; the factors actually needed were ×9.1 and ×4.1.

The bias allowance exists because of a caught mistake. The first ceiling-height sigma came out at
**0.1 mm** — the standard error of 250,000 points. Arithmetically correct, and confident garbage:
no phone measures to a tenth of a millimetre. Averaging removes noise; it does not remove a
systematic offset. That offset is now **measured, not assumed**, and so is the height it feeds.

**G-CEIL: 5 of 5 ARKitScenes walks within 15 mm, mean −4.3 mm, worst 6.6 mm.** Device depth and
FARO-derived laser depth are fused with the same poses on the same frames and both go through
*our* floor and ceiling fit, so the number is device-minus-laser, not either height alone. The
correction is **leave-one-venue-out** — a walk is corrected with the offset measured on the
*other* venue's walks, never its own, because one fitted on the test walk would absorb the
error being reported. The ablation is what makes it a measurement:

| | G-CEIL | G-CEIL-SPREAD |
|---|---|---|
| **corrected, held out** | **5/5 within 15 mm, mean −4.3 mm — MET** | 10.3 / 12.0 mm — not met |
| depth as recorded | 1/5, mean −22.3 mm — not met | 9.7 / 8.4 mm — met |

G-CEIL-SPREAD asks the report to say whether we are **biased** or **unrepeatable**, and the brief
is clear that both fail. Uncorrected we are **repeatable and biased**, by −22.3 mm; the
correction removes the bias and costs 2–4 mm of repeatability, leaving us 0.3 mm and 2.0 mm over
a 10 mm target. Accuracy was the right thing to buy with that trade, and the cost is stated.

**One ceiling per room, not one per capture.** G-CEIL has always read "≤ 1.5 cm **per room**",
and until now the pipeline fitted a single histogram over the whole cloud and wrote that number
onto every room — **3.087 m on all five rooms** of `c7d28f72c6`. Fitting each room on the points
over its own floor cells publishes **2.278 to 3.096 m**, and **two rooms were out by 80 cm**,
previously published as measurements with a ±7 mm interval. Averaging would never have found it:
a unimodal fit over a multimodal property returns the **mode**, here the 36.96 m² living room
holding 26% of the cloud; the other three agreed by accident, under the same slab. Each room now
also publishes **what share of its own footprint the fitted plane was seen over** — 21% to 87%,
because a ceiling over 87% of a shower room is a different claim from one over 21% of a living
room, and a point count cannot tell them apart. Per-room table: [`gates.md`](gates.md).

**The floor stays per storey, deliberately** — poured in one go, the whole footprint supporting
one peak, so splitting it per room would add variance and remove nothing. Ceilings are the
asymmetric case: boxed-in bathrooms and kitchen soffits are ordinary construction. **A room that
saw no ceiling keeps the unobserved population typical** (2.55 m, `observed=false`, wide
interval) rather than inheriting a neighbour's measured height, which would look like an
improvement and be a bias: unobserved rooms are the small, high-sided, hard-to-sweep ones, the
same ones most likely to be boxed in. On `1a8384c3f6` and `c00a170fe1` no room saw a ceiling and
all ten stay `observed=false`, unchanged.

**Independently corroborated**, one way only: an independent submission's nine-room split of
this capture
agrees with our five heights **within 11 mm on every one**, including the two low ones — two
pipelines sharing no code, which is evidence the old 3.087 m was wrong, not merely coarse.
Per-height table and the caveat: [`gates.md`](gates.md).

**G-CEIL itself is unmoved, and that was checked rather than assumed.** The per-room fit is a
**new** entry point, `planes.ceiling_of`; `floor_and_ceiling` delegates its ceiling half to it
and is otherwise untouched, and `bench/ceiling_walks.py` reproduces `ceiling_walks.json` **byte
for byte** — still 5/5 within 15 mm, mean −4.3 mm.

**This took three attempts and the first two published wrong conclusions**, kept in the
repository with retraction notices because the reasoning in them reads convincing:
`bench/arkitscenes_laser.py` blamed multi-storey venues, `bench/ceiling_vs_laser.py` blamed the
upsampling split. What was actually wrong was three ARKitScenes pose-format facts — a
cam_from_world rotation, a translation in the camera frame, a z-up world — written out with what
each withdrawn attempt measured in [`gates.md`](gates.md). With the poses wrong the fused cloud
genuinely has no dominant floor layer: the symptom blamed on the venues twice. The data was
fine throughout.

**Credit:** that the full raw walks carry laser depth across the trajectory, and the three
conventions above, were learned from the ARKitScenes ingest and dataset-fetch scripts of an
independent submission to the same brief that measured this gate. The venues here are chosen by a stated rule rather than copied, and the pipeline
measured is ours — but the approach is theirs, and this project had already published twice that
the measurement was unavailable.

The fix was to stop inferring. The upsampling split publishes device and laser-derived depth for
the **same frames**, so the bias is a per-pixel subtraction with no floor to find and no venue
geometry to be wrong about, on 50 MB per scan rather than a 1.9 GB cloud. Result: **−18.0 mm
over 4.79 million pixels across 8 scans**, per-scan medians −14 to −27 mm. The device reads
short; the correction adds it back at ingest. Two wrong answers were caught on the way — an
inferred vertical axis picked Z for one scan and Y for another in the same venue, 790 mm apart,
while the mean looked like a respectable −20 mm bias ([`gates.md`](gates.md)).

Those eight medians are summarised two ways in `depth_bias.json` under names that cannot be
confused: a **range of 13.0 mm**, the honest headline that no single correction fits every scan,
and a **standard deviation of 4.10 mm**, what survives the correction and therefore what the
interval must carry. Only the range used to be published while the code constant was set from
the deviation, so a reader checking the 4 mm against the benchmark would have found 13 and
reasonably concluded it was invented — correct and unverifiable, most of the way to wrong.
`tests/test_traceability.py` re-derives both constants, and the sign, from the measurement.

## 5. The fix loop

**Gate chosen:** G-REPEAT-ROOMS — the same flat walked twice gave **3 rooms one time and 6 the
other**, while G-REPEAT-FOOTPRINT was *met* at 1.9%. Area repeats; its division into rooms does
not, and that pairing is the diagnosis.

**Declared** (commit `e44441b`, before any fix): the seed filter admits cores of 0.0064 m².
**Predicted:** 5 vs 5, gate met. **Result** (commit `c002a66`): **4 vs 5, gate still not met.**
Footprint improved to 0.8%.

**The declared root cause was factually wrong.** `max(min_cells // 4, 16)` with
`min_cells = 3000` is **750 cells = 0.30 m²**; the 16 never applies, and varying that threshold
0.25→0.50 changes nothing. The real lever was the erosion width: the declaration named the right
function and the wrong mechanism inside it.

**Three measurement bugs surfaced while testing**, each producing a plausible wrong answer, each
caught only by checking one harness against another — a harness that omitted drift correction
and read "before" as 7 vs 7 where the benchmark measured 3 vs 6; patched module constants that
silently did nothing, because Python binds default arguments at definition, so the measured
"before" was half the fix already applied; and so a declared before-state that was not the
before state. **A second attempt**, hierarchical splitting, was built, measured and **reverted**:
an experiment over 36 configurations predicted 7-vs-7 rooms and 1.4%, the shipped version gave
6-vs-7 and 6.2%. Same error again, a harness bypassing `pipeline.run`. The rule that follows is
narrow and useful — **a configuration sweep must call the same entry point the product calls** —
and it was *still* being broken, by the very script producing the evidence behind the
declaration. The clean-clone check found that third instance; the harness now asserts itself
against `scanplan run` and exits non-zero on divergence, because writing the rule down had
already failed twice.

**Postscript: the gate later moved, and not because of any of this.** The measured depth-bias
correction took G-REPEAT-ROOMS to 5-vs-5 (**met**) while G-REPEAT-FOOTPRINT went 0.7% → 3.2%
(**not met**). Exactly one of the two still passes and the correction flipped which — two gates
that trade places under 18 mm of depth were never measuring independent properties. That is a
side effect, not a third fix; claiming it as one would repeat the original error of naming the
right outcome and the wrong mechanism. Full account, with every ablation table and all three
harness bugs written out: [`fix_loop.md`](fix_loop.md) §6, §9, §10.

## 6. Validation

159 tests, all passing. The ones that matter assert **accuracy against geometry we constructed
and therefore cannot be wrong about** — the fixture writes a real Stray Scanner export, so the
actual loader is exercised, not a mock, and it writes depth **18 mm short, exactly as the device
does**, so the correction runs rather than being bypassed. Measured **through `pipeline.run`
with the product's own defaults**:

| Quantity | Truth | Measured | Error |
|---|---|---|---|
| Ceiling height | 2.500 m | 2.497 m | **−3.1 mm** |
| Floor height | 0.000 m | +0.0015 m | **+1.5 mm** |
| Floor area | 12.000 m² | 11.994 m² | **−0.05%** |
| Long dimension | 4.000 m | 3.950 m | −50 mm |
| Short dimension | 3.000 m | 2.920 m | −80 mm |
| Perimeter | 14.000 m | 13.740 m | −260 mm |
| Polygon | rectangle | 4 corners | — |

Area and the bounding extent disagree by about 4% by construction, not by error: `floor_area_m2`
is the floor actually covered by measurement, the polygon is the regularised outline. The
outline is the shape; the area is the measurement. **The depth-bias correction is optimal on
both quantities, and the ablation shows it** — same fixture, same entry point, only the
correction changed:

| depth correction | floor area | ceiling height |
|---|---|---|
| **0.018 m — measured, shipped** | **−0.05%** | **−3.1 mm** |
| 0.030 m — over by 12 mm | +0.69% | +17.3 mm |
| 0.000 m — none | −1.44% | −33.3 mm |

**A correction to an earlier claim in this report.** It said the area figure had been flattered
by two errors cancelling and gave the honest value as about −3%. That −3% was itself a
measurement artifact: the fixture under-sampled the floor, because its camera pitch cycled with
period 3 and the pipeline's default stride is also 3. Fixing the fixture moved area to −0.05%
and left the cancelling-errors explanation with nothing to explain. It is withdrawn, not
rewritten: the simpler reading, that the measured correction is right, is what the ablation
supports.

Damage detection is tested both ways: a 40 × 30 cm patch lifted 25 mm is found with extent
correct to 12 cm; a wardrobe 40 cm off the wall, and 4 mm of noise, are not reported; three real
undamaged flats produce zero regions. Also pinned: intervals never collapse below the measured
residual bias, log-scale intervals never go negative, unobserved values stay flagged, output is
deterministic, no committed result carries a machine-specific path, the compliance matrix's gate
table matches the benchmark, the committed document PDFs match their markdown, and the CLI never
prints a traceback — a stated failure beats a stack trace.

**A gate whose status moved with machine load.** A-RUNTIME's measured seconds had been moved out
of its result string so `gates.json` would reproduce — but the MET/NOT MET *status* still
depended on wall-clock, and CPU contention pushed the worst capture 44.6 s → 62.7 s and flipped
the gate. It now reports **NOT MEASURED under contention** off the load average
([`gates.md`](gates.md)). Removing a number from a string is not removing it from a decision.

**Reproduction.** `bench/clean_clone_check.sh` clones, installs from scratch, runs the tests,
regenerates the benchmarks and diffs committed against regenerated — classifying every result
file rather than counting files it never recomputed, after an earlier version reported "8
identical" where seven had merely been copied by the clone and compared with themselves.
"Every" is now enforced rather than asserted: the script compares its own list against
`bench/results/` and fails on a file it does not classify, because the hand-maintained list had
twice fallen behind the directory while still printing a total that added up. It has caught five
real defects, among them a bare `ModuleNotFoundError` on the default install, wall-clock seconds
inside a gate *result*, and the fix-loop harness measuring an unshipped pipeline.

## 6b. Head to head against an independent implementation

An app cannot be handed our input; another engineer's pipeline reading the same public capture
format can. So an independent submission to this brief measures the **identical** synthetic capture of a room 4.00 × 3.00 m with a
2.50 m ceiling by construction — truth is exact, not a tape reading.

**G-H2H-ENGINEER: beat or tie on 9 of 10 dimensions, 90%, MET.** Floor area −0.05% against
+29.4%; the one loss is ceiling height on a capture modelling an *unbiased* sensor, where our
18 mm correction is unwarranted. Two captures run on purpose — one modelling the device as
measured, one an ideal sensor — because running only the one that suits our correction would be
choosing the input without a number changing. This is **not** Part 3, which asks for a consumer
scanning app: that is magicplan, still PENDING for want of tape truth.

Reporting only the synthetic result would be advertising, so the same benchmark runs both
pipelines on the three supplied captures. Those carry no truth, so **nothing here is scored** —
but the divergence is the more useful question, and it is three losses for us, all measured.
**They split more rooms on every capture**: 3, 8 and 9 against our 2, 5 and 5, on footprints of
24.62, 56.98 and 56.07 m² against our 15.11, 48.04 and 49.65 m² — the gate this project declared
a fix for, predicted wrong, attempted again and reverted, done better by an independent
implementation (§7.7). **They fit ceiling height per room**, nine heights from 2.29 to 3.10 m on
`c7d28f72c6`, which is why §4 now fits per room too. **Their frame selection is adaptive by pose
change where ours is a fixed stride**, which is why `scanplan run` failed outright on a capture
whose sweep aliased with our stride (§6) and theirs did not; we shipped a `--stride` escape
hatch and a diagnostic, a mitigation and not a fix.

Two things stay in our favour: **dimensional accuracy against exact truth**, where the gap is
large and consistent across both generators and the convention is matched (their source
specifies inside faces, as ours does); and the **measured depth bias**, which they carry as a
13 mm uncertainty rather than correcting. Long form: [`walk_in.md`](walk_in.md).

## 6c. Wall-to-wall distance against laser truth

Ceiling height is the separation of two horizontal surfaces; a wall-to-wall distance is the same
measurement turned ninety degrees, and it is the quantity a floor plan is actually made of.
**A-WALL-LIDAR: MET — 10 of 10 within max(2 cm, 1%), median 8.6 mm**, on the distances between
the two walls *our device names*. That is a **stated narrowing**: the stricter reading, which
also charges us for naming a different pair than the laser would, is **8 of 10, worst 225 mm**,
and it is published in the same gate row.

Split by whether both clouds picked the same walls, **8 of 8 matched rows are within gate at
8.1 mm median** — so the two failures are plane-pair selection, not the sensor. What closed the
gap was selection that knows orientation: per-point normals, a facing test and extent gates took
the worst row from **975 mm to 3.4 mm**. The approach is not ours — normals from the depth grid
plus depth-edge rejection are from the independent submission's depth fusion, credited in
`bench/wall_normals.py`; an earlier attempt was rejected for claiming independence it did not
have. [`gates.md`](gates.md) carries both readings, the 12→10 denominator, the mechanism and
what the gate does not measure; [`declined_changes.md`](declined_changes.md) §2 records why this
definition was refused on first offer.

**Honest comparison:** the independent submission measured this gate too and met it, **4 of 4
distances** after depth correction — a quarter as many distances, done better. Plane-pair
stability is the clearest measured weakness in this submission.

## 7. Known failure modes

1. **No tape truth on the rooms we captured ourselves.** The largest remaining gap. It blocks the
   Part 3 head-to-head outright, where magicplan's own output is deliberately **not** used as
   truth, because it is the opponent and scoring an opponent against itself is circular. What it
   no longer blocks is absolute accuracy: three measurements rest on FARO laser depth — the
   **depth bias** per-pixel over 4.79 M pixels, **ceiling height** within 15 mm on 5 of 5 walks,
   and **wall-to-wall distance** (8 of 10, and 8/8 at 8.1 mm where our plane selection agrees).
   Public laser truth substitutes for a tape on everything except our own two rooms.
2. **The video tier is 27–60% from the LiDAR reference** on the same walks, and failed outright
   on the third capture with a stated `no floor found`. Its intervals are widened ×11 and do
   contain the reference 2/2, which is the correct response to an error of that size rather than
   a fix for it. Inferred depth is not measured depth, and the gap is the number this tier exists
   to report.
3. **The photo tier under-reports room extent by 3–4×. G-WALL-PHOTO: 0 of 6 within ±8%, median
   error 75.5%.** Getting there took three wrong answers, and the retraction matters more than
   the number: this report once **published that the inferred depth under-estimates scale**, and
   measured per-pixel against LiDAR depth on the same twelve stills it runs about **1.26× LONG**.
   The depth model is not the problem. The real cause is structural — a single levelled view
   spans **2.2–2.9 m** in plan where the six-frame *posed* LiDAR reference spans **4.2–4.7 m**,
   because with no poses the tier cannot merge views and its box is bounded by what one viewpoint
   can reach. That is the limit `scanplan/ingest/photos.py` has always declared in its docstring,
   now quantified. A genuine camera-orientation bug was found and fixed along the way and moved
   the gate only 76.8% → 75.5%, which is itself evidence about where the constraint sits; all
   three wrong answers are written out in [`gates.md`](gates.md). The gate stays NOT MET, and the
   reference is the LiDAR tier on the same frames — a reference, not truth, since nobody has
   taped this property.
4. **The photo tier does not stitch, by construction.** Two folders in, two disconnected groups
   out. With no camera poses nothing in the input says how rooms relate, and an L-shaped room
   returns as its bounding box. The output carries an error-severity warning saying so rather
   than laying out a plausible arrangement.
5. **The two walks of one flat do not agree about what the rooms are, and G-REPEAT-ROOMS passing
   at "5 vs 5" is a count coincidence.** Both return five rooms; paired by area rank they are
   37%, 76%, 8%, 33% and 44% apart, and one walk keeps as a single room roughly what the other
   splits in two — while the total footprint agrees to 3.2%. The gate asks for the count, so it
   is met on its wording and the wording is a weak proxy; the gate table's result string now says
   "counts only" so it cannot be read as agreement (`bench/same_flat.py`). This is also why
   per-wall **G-REPEAT is not measurable** here rather than merely unmeasured: even perfectly
   registered, a wall bounding a room in one walk runs through the middle of a room in the other,
   so there is no counterpart to match, and pairing by rank anyway would rest on a correspondence
   that benchmark disproves.
6. **G-OPEN is measured and failed: 0 of 12 openings agree within 2 cm** between the two walks,
   the closest pair 4 cm apart. It needed no tape truth — only comparing one walk against the
   other, which had not been attempted. Separately and worse, **every opening we measure is
   0.16–0.52 m wide where a doorway is 0.6–0.9 m**: the widths are not just irreproducible, they
   are too small. The clear-width measurement is under-reporting and that is unfixed.
7. **Rooms under-split** — 5 found on a capture where this project's own fix-loop declaration put
   the reference at 9. **That 9 has no source recorded anywhere in this repository.** It first
   appears in `fix_loop_declaration.md`, which is committed-before-the-fix and therefore never
   edited, and has been repeated since without anyone establishing where it came from. It is
   cited here because it is used *against* us, but an unsourced number is weak evidence in either
   direction and should not be relied on. What *is* measured: an independent implementation
   reports 9, 8 and 3 rooms on the three supplied captures where we report 5, 5 and 2
   (`bench/results/head_to_head_engineer.json`). We under-split; that much is not in doubt. The
   safer failure: a merged pair still reports a correct combined area; an invented room does not.
8. **Damage class is shape-derived.** A stain that has not lifted the plaster is geometrically
   invisible. Every region says `class_source: "shape"` with confidence ≤ 0.5, and detection has
   no verified true-positive rate because no real damaged capture was obtainable.
9. **Mirrors and glass are not detected.** Two geometric tests were built; neither separates a
   reflection from ordinary geometry — one fired on 19–30% of every capture, the other on 10–13%.
   The flag is **disabled deliberately** and every run warns that mirrors are undetected, which
   is worth more than a detector that fires everywhere. Wet/glossy floor and low light *are*
   detected and warned about.
10. **Room area is under-reported by design** — about −3% on known geometry. Coverage-based area
   cannot exceed what was seen, so occluded floor is missing rather than estimated.

## 8. What I would do next, in order

1. **Get tape truth onto two rooms.** It converts a whole column of *not measured* into numbers
   and unblocks the head-to-head. Highest value per hour by a wide margin — everything else here
   improves a number that is already known.
2. **Stabilise the wall-plane selection**, now the clearest measured weakness. A-WALL-LIDAR
   agrees with the laser to **8.2 mm median** where both clouds choose the same pair of walls and
   fails completely on the rows where they do not. The sensor is fine; the densest-plane heuristic
   is not — a raw histogram argmax, so where two parallel surfaces 0.19–0.99 m apart have
   near-equal support the choice turns on a margin as small as **2.2%**. It is **not** established
   that fixing it would move the gate to most of 12, and an earlier version of this list
   over-claimed exactly that; [`gates.md`](gates.md) states how far the evidence goes.
3. **Replace the global `door_max_m`** with a split that adapts to local room scale. Two parameter
   attempts have failed; §5 is clear that this is not a parameter problem.
4. **Pose estimation for the video tier**, so it works on a bare clip rather than needing a pose
   track. That is structure-from-motion, and it would need its own validation before any number
   it produced could be trusted.
