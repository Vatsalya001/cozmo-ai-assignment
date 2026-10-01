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

## Gates the benchmark reports, refined from the ones above

`bench/gates.py` reports four IDs that are not in either table, because a gate above could not
be measured as literally written and was narrowed to something the available data can answer.
They were previously reported with no definition anywhere — including
**G-REPEAT-FOOTPRINT, one of the three gates that currently fails** — so a reader checking a
failing number had nothing to check it against.

| ID | Refines | Target | Why the parent could not be used as written |
|---|---|---|---|
| G-REPEAT-FOOTPRINT | G-REPEAT | Two walks of one flat agree on total footprint within **2%** | G-REPEAT asks for *every wall* within max(1 cm, 0.5%). Two independent walks produce two independent room decompositions with no shared wall identities, so there is nothing to pair up. Total footprint is the strongest quantity that survives having no correspondence |
| G-REPEAT-ROOMS | G-REPEAT | Both walks report the **same room count** | The companion to the above. Area repeating while its division into rooms does not is a specific, diagnosable failure, and separating the two is what made it visible |
| A-CALIB-VIDEO | A-CALIB | The nominal 90% interval **contains the LiDAR reference** on every capture where the video tier produced a plan | A-CALIB asks for 85–95% coverage of *truth*. There is no truth for these captures, and with 2 usable captures a coverage percentage would be meaningless anyway. Containing the reference is weaker and is honestly weaker: it says the interval is wide enough for the error we can see, not that it is correctly sized |
| A-DMG-DETECT | A-DMG | Staged damage found with the right class | Reported as **NOT BUILT**: B.2 was never captured, because the only damaged room available is in a property with no LiDAR-capable device. The row exists so the absence is visible in the gate table rather than only in the compliance matrix |

**2% for G-REPEAT-FOOTPRINT is our decision.** It is roughly twice the 1%/A-WALL-LIDAR linear
target, on the standing assumption that area error runs about twice linear error — the same
reasoning as A-AREA above.

## Gates defined above that the benchmark does not report

Stated so that an absent row is not read as a quiet pass. None of these is scored by
`bench/gates.py`:

| ID | Where it is actually settled |
|---|---|
| G-CONTRACT | Not numeric. Mapped item by item to files in `docs/compliance_matrix.md` Part 2 |
| G-INSTALL | `bench/clean_clone_check.sh` — clone, install and first result from scratch |
| A-FLAG, A-SCOPE | Asserted by unit tests rather than a benchmark; both are properties of the logic, not measurements |
| A-AREA, A-ADJ | **Need ground truth that does not exist.** Equivalent to the NOT MEASURED rows |
| A-DMG | Superseded by the A-DMG-DETECT row above |
| A-CALIB | Realised as A-CALIB-VIDEO above; the LiDAR tier has no truth to be calibrated against |

`tests/test_traceability.py` fails if any gate reported by the benchmark stops having a
definition on this page, so this reconciliation cannot silently rot the way it had.

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
