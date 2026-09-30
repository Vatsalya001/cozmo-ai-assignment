# Gates: pass/fail targets

The brief says *"Round 1 gates apply, with five additions"* and *"JSON to the published
schema"*, but neither the Round 1 gate list nor the schema was provided. Both are therefore
defined here, and every target is marked as coming **from the brief** or as **our decision**
with the reason for the value. The technical report repeats these definitions.

Measurement conventions (wall length, opening width, footprint, error) are fixed in
[`gt/README.md`](../gt/README.md) and are used identically for our pipeline, the ground
truth, and the head-to-head app.

Output schema: [`schema/output.schema.json`](../schema/output.schema.json) — ours, v0.1.0.

## From the brief

| ID | Gate | Tier | Target |
|---|---|---|---|
| G-OPEN | Opening widths | LiDAR | Error ≤ 2 cm on ≥ 85% of openings. **A missed or a phantom opening each count as a miss** |
| G-CEIL | Ceiling height | LiDAR | Error ≤ 1.5 cm per room |
| G-CEIL-SPREAD | Ceiling repeatability | LiDAR | Spread across captures of the same room ≤ 1 cm. The report must state whether we are **biased** or **unrepeatable** — both fail |
| G-REPEAT | Wall repeatability | Same tier, 2 captures | Every wall agrees within 1 cm or 0.5% |
| G-DRIFT | Drift accountability | LiDAR, video | Method stated **and** a stitched-footprint ablation with correction on and off. "Poses used as-is" is an automatic fail |
| G-PHOTO-STITCH | Whole-property stitch | Photo | One plan from per-room folders, correct adjacency, **no room overlaps**, footprint within ±8% with calibrated intervals |
| G-WALL-PHOTO | Wall lengths | Photo | Within ±8%, calibrated intervals |
| G-WALL-VIDEO | Wall lengths | Video | Within ±3%, calibrated intervals |
| G-H2H | Head-to-head | LiDAR, 2 rooms | Beat or tie a named, versioned consumer app on ≥ 70% of shared dimensions |
| G-CONTRACT | Output contract | All | Per-room plan, stitched plan, damage regions with class and metric extent, concealed flags naming the rule, scope keyed to surfaces, interval on every measurement, one command, JSON to schema, rendered plan |
| G-INSTALL | Fresh setup | All | README to a first result on a clean machine in **< 15 min** |

## Our decisions

| ID | Gate | Tier | Target | Why this value |
|---|---|---|---|---|
| A-WALL-LIDAR | Wall lengths | LiDAR | ≤ max(2 cm, 1%) | The brief loosens video to ±3%, so LiDAR must be tighter. Matches reported incumbent accuracy of 1–3 cm |
| A-AREA | Room floor area | LiDAR / video / photo | ≤ 2% / 6% / 8% | Area error is roughly twice linear error; photo capped at the brief's ±8% footprint gate |
| A-ADJ | Adjacency | All | Every true connection found, no false ones, no overlaps > 0.05 m² | The brief requires correct adjacency at every tier |
| A-DMG | Damage detection | All | Every staged region found with the correct class, IoU ≥ 0.5 on the wall plane, extent within ±25%, ≤ 1 false region per room | The brief requires class and metric extent but sets no threshold |
| A-FLAG | Concealed flags | All | 100% of flags name a rule that exists in the rules file | Brief: "with the rule that fired" |
| A-SCOPE | Scope items | All | 100% reference an existing surface and a damage region or rule | Brief: "keyed to surfaces" |
| A-CALIB | Calibration | Each tier | Nominal 90% intervals contain truth 85–95% of the time, and widen from LiDAR → video → photo | Brief: calibration scored at every tier; "confident garbage on thin input caps your total score" |
| A-SCHEMA | JSON validity | All | 100% validate, and `ci_low ≤ value ≤ ci_high` | Brief: "JSON to the published schema" |
| A-DET | Determinism | All | Same input twice → identical JSON except runtime | Required for G-REPEAT and a regenerable fix loop |
| **A-RUNTIME** | **Runtime** | **All** | **LiDAR ≤ 60 s, photo ≤ 3 min, video ≤ 5 min on the submission laptop, CPU only** | **The walk-in runs live while examiners measure. A tier that takes 13 minutes is a scoring problem regardless of its accuracy** |

## How the unclear parts of the brief are read

1. **"within 1 cm or 0.5% per wall"** is read as **max(1 cm, 0.5% × L)** — whichever is looser.
   The benchmark also reports how many walls pass the stricter reading, min(1 cm, 0.5% × L).
2. **Opening and ceiling gates** are applied strictly at the LiDAR tier, since the brief only
   loosens wall lengths for video and photo. The same errors are still reported at those tiers
   against the LiDAR thresholds, so nothing is hidden.
3. **Footprint** is the sum of room floor areas at inside faces. The outer outline including
   wall thickness is also reported so either reading can be checked.
4. **Round 1 gates** are taken to be the contract items listed in Part 2 of this brief
   (G-CONTRACT). The compliance matrix maps each one to a file.
