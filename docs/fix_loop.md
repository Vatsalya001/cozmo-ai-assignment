# Fix loop: outcome and post-mortem

The declaration, committed before any of this was built, is
[`fix_loop_declaration.md`](fix_loop_declaration.md) at commit `e44441b`. Nothing in it has
been edited since.

---

## 5. Result

| | Before | Predicted | **After** |
|---|---|---|---|
| Rooms, 1a8384c3f6 vs c7d28f72c6 | 3 vs 6 | **5 vs 5** | **4 vs 5** |
| G-REPEAT-ROOMS | NOT MET | **MET** | **NOT MET** |
| G-REPEAT-FOOTPRINT | 1.9% apart, MET | 1–4%, MET | **0.8% apart, MET** |
| Footprint 1a8384c3f6 | 47.85 m² | 46–50 | 47.54 m² |
| Footprint c7d28f72c6 | 48.78 m² | 47–51 | 47.93 m² |
| A-RUNTIME | 35.7 s | unchanged | 42.8 s, still MET |
| Tests | 27 pass | 27 pass | 27 pass |

**The gate did not move. The prediction was wrong.**

Two things did improve, and both are real: the room-count disagreement narrowed from 3 to 1,
and footprint agreement improved by a factor of 2.4, from 1.9% to 0.8%. The footprints were
inside the predicted ranges. The headline number was not.

## 6. Post-mortem: what went wrong

### The declared root cause was factually wrong

The declaration said the seed filter in `split_rooms` admitted cores as small as
**16 cells, 0.0064 m² — "a patch of floor the size of a postcard"**. That was a misreading of
our own code. The bound is `max(min_cells // 4, 16)`, and with a 1.20 m² minimum room area at
2 cm cells, `min_cells` is 3000, so `min_cells // 4` is **750 cells — 0.30 m²**. The 16 never
applies. The filter was already sensible; the postcard does not exist.

The ablation confirms the filter was never the lever. Holding the erosion width at 0.95 and
varying the seed threshold across the range the fix was supposed to correct:

| seed area | rooms | footprint gap |
|---|---|---|
| 0.30 m² (as shipped before) | 3 vs 6 | 1.9% |
| 0.25 m² | 4 vs 6 | 2.1% |
| 0.50 m² | 3 vs 4 | 3.1% |

Moving it in either direction changes little and helps nothing.

### What actually moves the gate

The erosion width. Measured through the shipped pipeline:

| seed | door | rooms | footprint gap | |
|---|---|---|---|---|
| 0.30 | 0.95 | 3 vs 6 | 1.9% | the before state |
| 0.30 | 0.80 | 4 vs 5 | 3.4% | rooms closer, footprint worse |
| **0.30** | **0.70** | **4 vs 5** | **0.8%** | **shipped** |
| 0.50 | 0.70 | 3 vs 4 | 3.1% | |

So the declaration named the right *function* and the wrong *mechanism inside it*. Under the
brief's scoring that is a wrong prediction, not a near miss.

### Three measurement bugs found while testing the fix

Each produced a plausible, wrong answer, and each was caught only by checking one harness
against another. They are recorded because they are the reusable lesson.

1. **The ablation harness did not match the shipped pipeline.** It rebuilt the geometry by
   hand and omitted drift correction. It reported the before state as 7 vs 7 rooms where
   `bench/gates.py` measured 3 vs 6, on identical data.

2. **Patching module constants did nothing.** Python binds default arguments once, at
   definition, so `rooms.DOOR_MAX_M = 0.70` silently had no effect, while `MIN_SEED_AREA_M2`,
   read inside the function body, did change. The resulting "before" was half the fix applied.
   Both tunables are now explicit parameters of `pipeline.run`.

3. **The declared "before" was not the before.** Following from the misreading above, the
   first ablation used 0.0064 m² as the baseline seed threshold when the shipped code used
   0.30 m². Only after correcting it did the harness reproduce `gates.py` exactly — 3 vs 6,
   1.9% — which is the check that should have been run first.

### Why the fix still falls short

`door_max_m` is one global number, and rooms in these flats are not one size. Set it wide
enough to split a large room from a hallway and it erases a small bathroom; set it narrow
enough to keep the bathroom and two rooms joined by a wide opening stay merged. The two walks
see different amounts of each room's floor, so they land on different sides of that threshold
in different places. 4 vs 5 is that residual.

Fixing it properly needs a split that adapts to local room scale rather than a single global
erosion. Distance-transform peak seeding was tried for exactly this and over-segments badly —
the peak set of a distance field is a medial axis, so one room yields a line of seeds. The
next thing to try is a hierarchical split: erode progressively and record the width at which
each component separates, which gives each room its own scale instead of one for the building.

### Was the exercise worth it?

The gate did not move, so by the brief's rubric this earns marks for the post-mortem and none
for the prediction. But footprint agreement improved 2.4×, the room gap narrowed from 3 to 1,
and three measurement bugs were removed that would otherwise have corrupted every later
benchmark — including the one that made an ablation silently measure half a fix.

## 7. What ships

`door_max_m` 0.95 → **0.70**, and the seed threshold made explicit at its existing 0.30 m².
Both stay on: the after state is better than the before state on both measured gates, even
though one remains unmet.

## How to regenerate

```bash
git checkout e44441b && python bench/gates.py   # before, writes bench/results/gates.json
git checkout <fix commit> && python bench/gates.py   # after
git diff e44441b <fix commit> -- scanplan/      # the change
```

Committed results: `bench/results/fix_loop_before_gates.json` and `fix_loop_after_gates.json`.

---

## 9. After the fix loop: a second attempt at the same gate, reverted

The post-mortem above named hierarchical splitting as the next thing to try — erode
progressively and claim each component at the first width that separates it, so every room
gets its own scale instead of one for the building. It was built and measured.

**An experiment over 36 configurations found one that met both repeatability gates:**
widths 1.00 → 0.55 in steps of 0.15, seed 0.30 m², minimum room 1.80 m² — 7 rooms against 7,
footprint 1.4% apart. Against the shipped 4-against-5 at 1.6%, that looked like a clear win,
and it brought the room count closer to the reference of 9 — a figure taken from the declaration, where it is asserted without a source. See technical_report.md §7.5.

**Shipped through the real pipeline it was a regression:**

| | Rooms | Footprint gap | |
|---|---|---|---|
| Shipped single erosion | 4 vs 5 | **0.7%** | footprint MET |
| Hierarchical, as predicted by the experiment | 7 vs 7 | 1.4% | both MET |
| Hierarchical, **actually measured** | 6 vs 7 | **6.2%** | both NOT MET |

Reverted.

### Why the experiment was wrong, and why that is the real finding

**The experiment harness did not match the shipped pipeline.** It rebuilt the geometry by hand
and omitted drift correction, which the pipeline applies before fusion.

That is the *same error* as §6.1 — the one this post-mortem had already identified, written up,
and recommended against. Knowing the failure mode did not prevent repeating it, because the
convenient way to sweep 36 configurations is to bypass the pipeline, and the convenient way is
the wrong way.

The rule that follows is narrower and more useful than "be careful": **a configuration sweep
must call the same entry point the product calls.** `pipeline.run()` already takes
`door_max_m` and `min_seed_area_m2` as explicit parameters precisely so a sweep can go through
it; the hierarchical experiment did not use them because the new parameters were not wired
that way yet, and so it measured something else.

### What this costs, stated plainly

G-REPEAT-ROOMS remains **NOT MET at 4 against 5**. Two attempts have now failed to move it:
the declared fix narrowed the gap from 3 to 1 without closing it, and this one made both gates
worse. The honest conclusion is that room splitting on this data is not a parameter problem,
and a third attempt would need a different method rather than a different constant.

> **Superseded by §10.** That paragraph was true when written. The measured depth-bias
> correction has since moved the gate without anyone touching the room-splitting code, and
> §10 records both the new state and why the change is not a third attempt.

---

## 10. The gate moved, and not because of anything in §6 to §9

A sensor correction landed after the fix loop closed: device depth was measured at **18 mm
short** of FARO laser truth and is now corrected at ingest (`bench/depth_bias.py`,
4.79 million pixels across 8 scans). Nothing in the room-splitting code changed. The gates
moved anyway:

| | §9 state | After the bias correction |
|---|---|---|
| Rooms, 1a8384c3f6 vs c7d28f72c6 | 4 vs 5 | **5 vs 5** |
| G-REPEAT-ROOMS | NOT MET | **MET** |
| Footprint gap | 0.7%, MET | **3.2%, NOT MET** |
| G-REPEAT-FOOTPRINT | MET | **NOT MET** |

**Exactly one of the two still passes, and the correction flipped which.** That is reported
rather than absorbed, because it is the most informative thing either gate has produced: the
two are not independent, and 18 mm of depth is enough to swap them. A pair of gates that trade
places under a sensor correction was never measuring two separate properties.

The correction stays either way. It is a measured property of the device, and reverting a
correct correction to recover a gate is tuning to the benchmark — the failure this post-mortem
already documents twice.

**This is not a third attempt at G-REPEAT-ROOMS.** The gate passing here is a side effect, not
a fix, and claiming it as one would be the §6 error in a new costume: naming the right outcome
and the wrong mechanism. The §9 conclusion stands unchanged — room splitting on this data is
not a parameter problem.

### The §9 rule was still being broken, in this very directory

§9 ended by stating a rule: **a configuration sweep must call the same entry point the product
calls.** `bench/fix_loop_diagnosis.py` — the script that produced the evidence behind the
declaration — was itself breaking it. It rebuilt the geometry by hand and omitted drift
correction, the same omission as §6.1 and §9.

The clean-clone check found it (`bench/clean_clone_check.sh`), which is what that check is for:
the committed `fix_loop_diagnosis.json` did not match a fresh run, and chasing the difference
turned up more than stale numbers. At the shipped `door_max_m` the harness reported **4 rooms
from each capture while `scanplan run` reported 5 from each.** Both "agree", so the conclusion
§6 drew from this evidence survives — but it survived by luck, on a pipeline nobody ships.

Fixed two ways, because writing the rule down had already failed to enforce it once:

1. The sweep calls `pipeline.run` — six configurations × two captures, the product's own entry
   point. Slower, and the correct trade for the measurement the shipped `DOOR_MAX_M` rests on.
2. `check_harness_matches_product()` asserts the harness and `scanplan run` return the same
   room count at the shipped configuration, and the script **exits non-zero** if they diverge.
   The rule is now a failing build rather than a paragraph.

The re-measured sweep, through the real pipeline:

| `door_max_m` | 1a8384c3f6 | c7d28f72c6 | |
|---|---|---|---|
| **0.70** | **5** | **5** | **agree — shipped** |
| 0.80 | 4 | 5 | |
| 0.95 | 4 | 5 | the pre-fix-loop value |
| 1.10 | 5 | 5 | agree |
| 1.30 | 4 | 3 | |
| 1.50 | 2 | 3 | |

Two widths now agree, and the shipped 0.70 is the narrower of them — the conservative choice,
consistent with the pipeline's stated preference for under-splitting. That the pre-fix-loop
0.95 still disagrees is the one claim in §6 that this re-measurement independently confirms.

### What this episode says about the rest of the benchmarks

Three harnesses have now been caught measuring a pipeline that was not shipped — §6.1, §9, and
this one — and all three failed the same way. The pattern is not carelessness; it is that
bypassing `pipeline.run` is always the convenient way to sweep a parameter. The only defence
that has actually worked is a mechanical one: an assertion inside the harness that compares it
to the product and fails. `bench/gates.py` calls `pipeline.run` directly and so cannot drift;
`fix_loop_diagnosis.py` now checks itself; any future sweep should do one or the other.
