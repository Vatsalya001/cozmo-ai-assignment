# Fix loop declaration

Committed **before** the fix is written or benchmarked, so the prediction below is on record
ahead of the result.

Date: 2026-10-01. Code at declaration: commit `HEAD` of this file's parent.

---

## 1. The worst-performing gate, with the failing number

**G-REPEAT-ROOMS — the same flat walked twice does not produce the same number of rooms.**

Measured by `bench/gates.py` over the two supplied whole-flat walks:

| | 1a8384c3f6 | c7d28f72c6 |
|---|---|---|
| Rooms found | **3** | **6** |
| Footprint | 47.85 m² | 48.78 m² |

Two walks of one flat, differing by a factor of two in room count.

This is the worst *measured* gate. Ten other gates read NOT MEASURED — they need tape truth,
or tiers that are not built — and a gate with no number behind it cannot be the subject of a
fix loop, because there would be nothing to move.

**Why this gate and not the footprint:** G-REPEAT-FOOTPRINT is **MET**, at 1.9% between the
same two walks. Floor area repeats; the division of that area into rooms does not. That pairing
is the whole diagnosis in one line — the measurement is stable and the *segmentation* is not.

## 2. Root cause, and the evidence for it

**Hypothesis.** Room count is unstable because the seed step of the split admits cores far too
small to be rooms, and how many such slivers survive depends on centimetre-scale differences
in floor coverage that differ between any two walks.

`split_rooms` erodes the floor by half a doorway width, treats each surviving connected
component as a room seed, then grows the seeds back under a watershed. The seed filter keeps
any component of at least `max(min_area_cells // 4, 16)` cells — with a 1.20 m² minimum room
area at 2 cm cells, that lower bound is **16 cells, or 0.0064 m²**. A patch of floor the size
of a postcard becomes a room.

**Evidence, measured on the two real walks before declaring** (`bench/fix_loop_diagnosis.py`):

1. **The surviving seed cores are mostly not rooms.** At the shipped `door_max_m = 0.95`:

   ```
   1a8384c3f6: 12 cores, areas 5.57 1.39 0.98 0.28 0.18 0.03 0.02 0.02 0.01 0.00 ...
   c7d28f72c6:  9 cores, areas 8.70 2.09 0.78 0.71 0.40 0.10 0.02 0.01 0.00 ...
   ```

   Three or four are plausible rooms. The rest are down to 0.00 m², and their number differs
   between the walks — 12 against 9.

2. **The instability is a function of the one parameter the seeds depend on.** Room count
   against erosion width, both walks:

   | `door_max_m` | 1a8384c3f6 | c7d28f72c6 | |
   |---|---|---|---|
   | 0.70 | 5 | 5 | stable |
   | 0.80 | 5 | 5 | stable |
   | **0.95** (shipped) | **3** | **5** | unstable |
   | 1.10 | 4 | 5 | unstable |
   | 1.30 | 4 | 3 | unstable |
   | 1.50 | 2 | 3 | unstable |

   The two walks agree at 0.70 and 0.80 and disagree at every wider setting. This is a
   measurement on the real captures, not an argument from a synthetic case.

3. **The underlying floor coverage is not the problem.** 53.7 m² against 56.0 m², and 49.2 m²
   against 51.1 m² after walls are cut — about 4% apart, consistent with the 1.9% footprint
   agreement. The input to the split is stable; the split is not.

**What this rules out.** Drift is not the cause: corrections on these captures top out at
12 mm (`bench/results/gates.json`), far below the scale at which a 0.95 m erosion changes
topology. Depth noise is not the cause either: the coverage areas agree to 4%.

## 3. The fix to ship

1. **Filter seeds by a real minimum room area.** A seed core must be at least 0.25 m² —
   smaller than any room, far larger than a postcard — instead of the current 0.0064 m².
2. **Set the erosion width to the value the data says is stable**: `door_max_m` from 0.95 to
   0.80, the widest setting at which both walks agree.

Both are parameter and filter changes inside `split_rooms`. Nothing else moves.

## 4. Prediction

Measured by `bench/gates.py` on the same two walks:

| | Before | **Predicted after** |
|---|---|---|
| Rooms, 1a8384c3f6 vs c7d28f72c6 | 3 vs 6 | **5 vs 5** |
| G-REPEAT-ROOMS | NOT MET | **MET** |
| G-REPEAT-FOOTPRINT | 1.9% apart | 1–4% apart, still **MET** |
| Footprint, 1a8384c3f6 | 47.85 m² | 46–50 m² |
| Footprint, c7d28f72c6 | 48.78 m² | 47–51 m² |
| A-RUNTIME | 35.7 s worst | unchanged |
| Tests | 27 pass | 27 pass |

**Confidence: moderate-to-high on the room count, lower on the exact footprints.** The
`door_max_m` sweep is a direct measurement of the outcome being predicted — both walks give 5
at 0.80 today — so the headline number is close to read off. The seed-area filter is the part
that is genuinely predicted rather than observed, and it may change the counts away from 5 in
either direction.

**Where this could still fall short.** Agreeing on five rooms is not the same as being right
about five rooms; the reference for these captures is nine. A narrower erosion also splits
less aggressively, so genuinely separate rooms joined by a wide opening will merge. This fix
targets *repeatability*, which is what the gate measures, and does not claim to fix room
counts being low.

## How to regenerate

```bash
git checkout <declaration commit> && python bench/gates.py   # before
git checkout <fix commit>         && python bench/gates.py   # after
git diff <declaration commit> <fix commit> -- scanplan/      # the change
```
