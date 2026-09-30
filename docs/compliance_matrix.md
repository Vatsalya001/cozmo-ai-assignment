# Compliance matrix

Every requirement in the brief → where it lives → what it is → status.

**Status key**

- **Met** — done, with evidence.
- **Built, not measured** — the capability exists and runs, but no ground truth exists to score it against. The number is absent, not hidden.
- **Built, gate not met** — it exists, it is benchmarked, and it misses its target. The failing number is given.
- **Partial** — some of the requirement is done; the rest is stated.
- **Not done** — missing, with the reason.

Paths are relative to the repo root. Gate definitions are in [`gates.md`](gates.md); results in
[`../bench/results/gates.md`](../bench/results/gates.md).

---

## Part 1 — capture and tiers

| # | Requirement | Where | Artifact | Status |
|---|---|---|---|---|
| 1.1 | Capture route: stock protocol, one page, followable by a non-engineer | `docs/capture_protocol.md` | Route 2. Stray Scanner for LiDAR, stock Camera app for video and photos, with install, walk, duration, what to avoid, hand-off | **Met** |
| 1.2 | Three input tiers, all mandatory, same output contract | `scanplan/detect.py`, `scanplan/pipeline.py` | Tier detected from the input. **Only the LiDAR tier is implemented**; video and photo detect correctly and then raise a stated error | **Partial** |
| 1.3 | Photos: 2–8 stills per room, per-room folders, stitched plan | `scanplan/detect.py` | Layout detected and validated; the tier itself is not built | **Not done** |
| 1.4 | Video: handheld walkthrough | `scanplan/detect.py` | Detected; tier not built | **Not done** |
| 1.5 | LiDAR: depth, poses, intrinsics | `scanplan/ingest/stray.py`, `scanplan/geometry/`, `scanplan/slam/` | Fusion, floor/ceiling, walls, rooms, openings, drift correction, damage, scope | **Met** |
| 1.6 | Intervals widen honestly as sensor data thins | `scanplan/measure.py`, `scanplan/pipeline.py` | Nominal 90% on every measurement; widening factors 1.0 / 4.5 / 5.1 by tier are wired but **only the LiDAR factor is exercised** | **Partial** |
| 1.7 | Device matrix: tier by hardware, honest accuracy per tier | `docs/device_matrix.md` | Table with what runs where and what is measured | **Met** |

## Part 2 — output contract

| # | Requirement | Where | Artifact | Status |
|---|---|---|---|---|
| 2.1 | Dimensioned per-room plan: walls, ceiling height, floor area, openings | `scanplan/pipeline.py`, `schema/output.schema.json` | `rooms[]` with polygon, walls and lengths, floor area, perimeter, ceiling height, openings and widths | **Met** |
| 2.2 | Stitched multi-room plan with correct adjacency | `scanplan/geometry/rooms.py` | `plan.adjacency`, one connected map per capture | **Partial** — adjacency is produced; no ground truth to verify it against |
| 2.3 | Per-surface damage regions with class and metric extent | `scanplan/damage/detect.py` | `damage[]` with surface, class, width, height, area, height above floor, confidence | **Built, not measured** — extent validated on synthetic defects; zero false positives on three real flats; true-positive rate on real damage unverified |
| 2.4 | Concealed-damage flags with the rule that fired | `scanplan/damage/rules.py`, `docs/damage_rules.md` | `concealed_flags[]` with `rule_id`, description, evidence; 6 rules, unit tested | **Met** as logic |
| 2.5 | Scope line items keyed to surfaces | `scanplan/damage/rules.py` | `scope[]` with `surface_id`, unit, quantity with interval, `because` | **Met** as logic |
| 2.6 | A confidence interval on every measurement | `scanplan/measure.py`, `scanplan/validate.py` | Nominal 90% intervals; validator enforces `ci_low <= value <= ci_high`; a test walks the whole document | **Met** |
| 2.7 | One command per capture | `scanplan/cli.py` | `scanplan run <capture>` | **Met** |
| 2.8 | JSON to the published schema | `schema/output.schema.json`, `scanplan/validate.py` | Validated before write, every run | **Met** (schema is ours; Cozmo published none) |
| 2.9 | Rendered plan | `scanplan/export/render.py`, `scanplan/export/report.py` | `plan.svg` dimensioned, `summary.md`, and a one-page `report.pdf`/`report.png` carrying the plan, room table with ranges, damage and the warnings | **Met** |

## Part 2 — benchmark set composition

| # | Requirement | Where | Status |
|---|---|---|---|
| B.1 | One multi-room capture, 3+ rooms plus a connector | supplied captures `1a8384c3f6`, `c7d28f72c6` | **Met** — whole flats with hallway |
| B.2 | One furnished room with staged damage, two classes | — | **Not done** — the only damaged room available is in a property with no LiDAR-capable device. Detector validated on synthetic defects instead |
| B.3 | The same rooms at all three tiers | — | **Not done** — video and photo tiers not built |
| B.4 | At least one room captured twice at the same tier | `1a8384c3f6` and `c7d28f72c6`, two walks of one flat | **Met** |
| B.5 | Laser or tape ground truth on everything | `data/arkitscenes/`, `data/own/` | **Partial** — FARO laser truth obtained for ARKitScenes, but no admissible scan (see below). Tape measurements of our own two rooms outstanding |

## Part 2 — gates

Generated by `bench/gates.py`; full table in [`../bench/results/gates.md`](../bench/results/gates.md).

| Gate | Result | Status |
|---|---|---|
| A-RUNTIME | worst 42.8 s against a 60 s budget | **Met** |
| A-DET | byte-identical across runs | **Met** |
| A-SCHEMA | 3/3 documents valid | **Met** |
| G-DRIFT | method stated, footprint ablation on/off, 5–124 loop closures | **Met** |
| G-REPEAT-FOOTPRINT | two walks of one flat agree to 0.8% | **Met** |
| G-REPEAT-ROOMS | 4 rooms vs 5 | **Built, gate not met** |
| G-CEIL | no laser or tape truth for the supplied captures | **Not measured** |
| G-CEIL-SPREAD | only one capture saw a ceiling | **Not measured** |
| G-OPEN | no tape truth | **Not measured** |
| A-WALL-LIDAR | no tape truth; synthetic room gives −40 mm on 4.00 m and −70 mm on 3.00 m | **Not measured** |
| G-WALL-VIDEO, G-WALL-PHOTO, G-PHOTO-STITCH | tiers not built | **Not measured** |
| G-H2H | magicplan captured both rooms; tape measurements outstanding | **Not measured** |
| A-DMG-DETECT | no real staged-damage capture | **Not measured** |

## Part 3 — head-to-head

| # | Requirement | Where | Status |
|---|---|---|---|
| 3.1 | 2 rooms, LiDAR tier vs one consumer app, named and versioned, export submitted, error by dimension, beat or tie ≥70% | `data/own/magicplan/`, `data/own/magicplan_results.md` | **Partial** — magicplan 2026.38.0 captured both rooms; DXF, Sketch PDF and Report PDF exported and committed; its numbers recorded. The comparison table needs our tape measurements, which are outstanding. Deviation to declare: our device has no LiDAR, so the comparison will run at whichever tier we can capture, not the LiDAR tier the brief specifies |

## Part 4 — fix loop

| # | Requirement | Where | Status |
|---|---|---|---|
| 4.1 | One-page declaration: worst gate with failing number, root-cause hypothesis and evidence, fix and predicted number | `docs/fix_loop_declaration.md`, commit `01cee6f` | **Met** — committed before the fix; root cause measured on the real captures, not argued from a synthetic case |
| 4.2 | Ship the fix | commit `aae8622` | **Met** |
| 4.3 | Before run, after run, both regenerable, readable diff | `bench/results/fix_loop_before_gates.json`, `fix_loop_after_gates.json`, `bench/gates.py` | **Met** |
| 4.4 | Say why it fell short | `docs/fix_loop.md` §6 | **Met** — the gate did not move and the prediction was wrong. The declared root cause was factually wrong (a misread threshold), the real lever was the erosion width, and three measurement bugs found while testing are documented |

## Part 5 — process evidence

| # | Requirement | Where | Status |
|---|---|---|---|
| 5.1 | Commit as you work; history that could belong to the person who built it | git history | **Met** — 21 commits, each carrying its own evidence and reasoning; predictions committed before results |

## Deliverables

| # | Deliverable | Where | Status |
|---|---|---|---|
| D.1 | Compliance matrix | this file | **Met** |
| D.2 | Capture route and device matrix | `docs/capture_protocol.md`, `docs/device_matrix.md` | **Met** |
| D.3 | README to a first result in <15 min on a clean machine, one command per capture | `README.md` | **Met** — verified in a fresh venv |
| D.4 | Reproduction bundle | `bench/reproduce.sh` | **Met** — one script regenerates every reported number, and verifies the input checksums before running anything |
| D.5 | Benchmark report: gates at all three tiers, repeatability, head-to-head, timing | `bench/results/gates.md` | **Partial** — LiDAR gates, repeatability and timing present; head-to-head empty; video and photo rows absent |
| D.6 | Fix loop bundle | `docs/fix_loop_declaration.md`, `docs/fix_loop.md`, `bench/results/fix_loop_*.json` | **Met** |
| D.7 | Technical report, max 6 pages | `docs/technical_report.md` | **Met** |
| D.8 | Raw benchmark data | supplied captures, `data/arkitscenes/`, `data/own/`, `data/captures_manifest.json` | **Partial** — sensor data and checksums yes; no tape truth yet |

## Constraints

| # | Requirement | Status |
|---|---|---|
| C.1 | Handheld consumer capture only; any pretrained model with disclosure; runs without our infrastructure | **Met** — no model is used at all so far; everything is geometry and runs locally |
| C.2 | Weights and large binaries fetched by script | **Met** — datasets gitignored, fetched by Apple's own script; no weights needed yet |
| C.3 | Mirrors, glass, wet-look surfaces, low light covered | **Partial** — wet/glossy floor and low light are detected from the data and warned about. Mirrors and glass are **not** detected: two geometric tests were built and neither separates a reflection from ordinary geometry, so the flag is disabled and every run warns that mirrors are undetected rather than shipping a detector that fires on every capture |
| W.1 | Walk-in test: all three tiers ready to run cold | **Partial** — LiDAR runs cold in 6–56 s with no weights and no network, and the CLI never shows a traceback. Runbook: `docs/walk_in.md`. Video and photo fail with a stated error |

---

## The honest summary

What works: the **LiDAR tier, end to end**, with a validated output contract, drift correction
with its ablation, a complete fix loop, and 38 tests including accuracy checks against a room
of exactly known dimensions (ceiling −3 mm, area +0.05%).

What does not: **two of three mandatory tiers are not built**, so roughly half the brief's
accuracy surface is absent. Most gates read *not measured* because no tape or laser truth
exists for the captures the pipeline actually runs on.

The single largest gap is the missing video and photo tiers. The second is ground truth.
