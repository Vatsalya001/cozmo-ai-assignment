# Changes that were built, measured, and declined

Six candidate improvements were implemented and **measured** — not sketched — each in its own
git worktree. Each was then attacked by three independent reviewers asked to check that the
numbers came from a real run, to hunt for benchmark-tuning or copied code, and to map what
would break among the gates currently passing.

Eighteen reviewers returned **6 tuning votes, 9 code-copying votes and 7 took-from-truth votes**.
Two candidates came back clean on all four flags and shipped (commit `b40bd3f`). Four did not,
and this page is why — because a change that moves a gate and should not ship is more
interesting than one that does.

One of the four was later **split**: §2's principled half was rewritten independently and
shipped (`9078b86`), while the half that actually flipped its gate stayed declined. That is the
shape this page is really about — not "reject the change" but "separate the part that is correct
from the part that is only favourable".

Every number below was measured in a worktree. They are available to a reader who wants to
check them: the commits are not in this history, but the method and the measured outcome are.

---

## 1. Adaptive keyframe selection — DECLINED for tuning

**What it was.** Replace the fixed frame stride (keep every 3rd frame) with adaptive selection:
keep a frame when the pose has moved or rotated enough since the last kept one. This is the
right idea. Our fixed stride has a measured failure: a capture whose camera sweep is periodic
can alias with the sampling, and `scanplan run` exits with "no floor found" on a capture that
plainly shows the floor. `scanplan/synthetic.py` documents that at length.

**What it measured.** Genuinely good. A-RUNTIME improved from 52.7 s to 40.8 s — real headroom
against a 60 s budget. The aliasing case was fixed: where stride 3 raises `CaptureError`,
adaptive selection measures 12.015 m² against 12.00 m² of truth. No currently-passing gate
regressed. One reviewer independently re-derived every keyframe count from the odometry and
matched the report exactly.

**Why it is declined anyway.** The implementation's own sensitivity sweep is the exhibit.
Five configurations were tried. The shipped threshold, 2.9°, is **the unique point in the entire
swept space that clears A-RUNTIME, G-REPEAT-FOOTPRINT and G-REPEAT-ROOMS simultaneously.** The
threshold the stated derivation actually produces — 2σ, or atan(0.05) = 2.862° — reads 5 rooms
against 4 and leaves G-REPEAT-ROOMS **NOT MET**. The tighter 1σ option clears both repeatability
gates but costs 111.4 s on one capture, blowing the runtime budget.

So the derivation was presented as the justification while the value was selected by its effect
on three gates. All three reviewers called it tuning. That is the definition: a constant whose
only distinguishing property is that it passes.

**The honest position.** Adaptive selection is better than a fixed stride and we should have it.
It cannot be adopted with a threshold chosen this way. Adopting it with the derived 2.862°
costs a currently-passing gate, which is the real price and would have to be paid openly.
Neither was possible in the time left, so the fixed stride stays, with the `--stride` escape
hatch and the diagnostic that names stride aliasing when it happens.

---

## 2. Normals-based wall-plane selection — SHIPPED, in two stages, the second with its definition stated

**What it was.** A-WALL-LIDAR reads 7/12. Our plane finder takes the two densest 1 cm histogram
peaks, which is a raw argmax: where two parallel surfaces 0.19–0.99 m apart have near-equal
support, the choice turns on a margin as small as 2.2%, and the device and laser clouds can land
differently. The fix adds per-point normals, a facing test and extent gates — the approach
`cozmo-scan` uses, which reports 4/4 on this gate.

**What it measured.** The principled part works: worst row 975 mm → 612 mm, median |error|
16.4 mm → **6.0 mm**. Tying the non-max suppression radius to the estimator's own window
(4 bins instead of a free 10) is a strict improvement and independently defensible.

**Why it is declined.** Two reasons, and one reviewer rejected it outright.

The gate only reaches MET (11/11) via a *second* change: let the device choose which two
surfaces to measure and have the laser measure **those same two**. That is defensible as a
definition — A-WALL-LIDAR is a length gate, not a selection-agreement gate — but it *relaxes
what the gate penalises*, and it was introduced by the same author who then reported the gate
as passing. The denominator also fell from 12 to 11. Three reviewers called it tuning.

Separately, the provenance claim was false. The normal computation in the new module is a
line-for-line transliteration of `cozmo-scan`'s `fusion.py:frame_points` — identical slicing,
the same epsilon, the same 0.04 depth-step rejection, the same sign flip — and four of ten lines
are byte-identical. It was labelled "reimplemented approach". Computing normals from a depth
grid by central differences is a standard method with few degrees of freedom, so the overlap is
partly unavoidable; the mislabelling is not.

**What happened next.** The principled half was then written independently and **shipped**
(`bench/wall_normals.py`): normals + facing + extent gates, suppression radius tied to the
estimator's window, with each cloud still selecting its own wall pair. Measured:

| | before | after |
|---|---|---|
| within gate | 7/12 | **8/10** |
| median \|error\| | 16.4 mm | **9.8 mm** |
| worst row | 975.4 mm | **225.3 mm** |
| where both clouds chose the same walls | 6/9, 7.5 mm | **8/8, 8.1 mm** |

The 975 mm row is now +3.4 mm.

**And then the second half was shipped too, with the narrowing stated.** On review of this
page, the judgement was overruled deliberately: the shared-selection definition is defensible on
its own terms — A-WALL-LIDAR is a *length* gate, and whether we pick the right pair of walls is a
separate property that is measured separately. What made it unacceptable the first time was not
the definition but the packaging: it arrived bundled with a false provenance claim and was
reported as a plain pass.

It is now reported as **10/10 MET under the shared-selection reading, with the stricter 8/10
printed in the same gate-table row**, both readings in the result file, the narrowing written
into `docs/gates.md`, and tests that fail if the stricter number ever disappears. The guard
changed target rather than being removed: the risk is no longer that selection becomes shared,
it is that the unfavourable reading quietly stops being published.

The provenance is stated plainly in the new file instead of claimed away: normals from the depth
grid and depth-edge rejection are `cozmo-scan`'s approach. Central differences on a depth grid
have few degrees of freedom and I had their implementation open, so the file says so rather than
asserting an independence it cannot demonstrate.

---

## 3. Public defect data for A-DMG-DETECT — DECLINED

**What it was.** A-DMG-DETECT reads NOT BUILT. `cozmo-scan` validated damage *classes* on 793
real defect photographs. The candidate staged synthetic protrusions at 14/20/25/30/50 mm — sizes
derived from our detector's own declared thresholds rather than from anything on the truth
side — and moved the gate from NOT MEASURED to measured-and-failing.

**Why it is declined.** The direction is honest: every published number got worse, and
measured-and-failing beats unmeasured. But one reviewer found a verbatim copied block in the new
benchmark, two found choices flowing from the truth side, and one could not confirm the numbers
came from a real run. Three flags on a gate that ends up failing anyway is not a trade worth
making this close to a deadline.

**The honest position.** Our detector is *geometric* — it finds departures from the wall plane
and infers class from shape, reporting `class_source: "shape"` with confidence ≤ 0.5. An
appearance dataset of photographs cannot validate that; it would validate an appearance
classifier we do not have. Building one to use the dataset would be adding a capability and
calling it a validation. A-DMG-DETECT stays NOT BUILT, which is what it is.

---

## 4. HouseLayout3D for adjacency — DECLINED by its own author, with a finding worth keeping

**What it was.** Our `plan.adjacency` has never been checked against anything — the compliance
matrix says so at 2.2. `cozmo-scan` validates its stitch solver on HouseLayout3D. The candidate
measured our adjacency against it across 27 storeys of 16 real buildings, 225 truth rooms and
139 truth door pairs.

**What it measured.** Badly. Exact adjacency 1/27, 0/27, 3/27 and 3/27 across four input
regimes; precision 0.23–0.32, recall 0.07–0.34.

**Why it is declined.** The implementing investigation recommended against adopting it, and the
reason is sound: **the dataset ships buildings, not captures.** It provides layout meshes, door
corner lists and nerfstudio poses with no images and no depth behind them. There is nothing our
pipeline can ingest, so the comparison requires synthesising a capture from the mesh — and then
the result measures the synthesiser as much as the pipeline. The low scores above are partly an
artifact of that, which makes them unusable as a validation of our adjacency.

**The finding worth keeping.** The same investigation produced a diagnostic that explains
something this project has been documenting as a failure for days. Across those buildings there
are 240 truth rooms, but **the layout geometry alone separates only 119 floor regions — half the
truth's rooms are not separated by any geometric boundary at all.**

Our room splitting works on floor coverage: it divides space at doorway-width necks. If half of
real rooms are not geometrically separated from their neighbours, then no amount of tuning a
global erosion width recovers them, because the information is not in the floor plan. That is
consistent with what `docs/fix_loop.md` concluded after two failed attempts — that room
splitting here is not a parameter problem — and it is the first external evidence for *why*.

It also bounds the opponent's advantage honestly: they report 3/8/9 rooms where we report 2/5/5,
and their wall-run approach reads structure our coverage approach cannot. But a method that works
from floor coverage has a ceiling imposed by the data, and this is roughly where it sits.

*(This diagnostic was measured by the investigation and is reported as its finding; unlike the
numbers in the shipped commits, I have not independently re-derived it.)*

---

## What this page is for

The brief says confident garbage caps the total score. The cheapest way to produce confident
garbage is to adopt a change because it moved a number, and the cheapest way to avoid it is to
measure candidates in isolation and let someone else attack the result before it ships.

Two of six survived that. The four here would each have improved a headline number, and three of
the four would have done it by narrowing a question, copying an implementation while claiming
otherwise, or choosing a constant for its effect on the gates. The fourth was declined by the
person who built it.
