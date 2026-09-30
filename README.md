# scanplan

Turn an iPhone LiDAR scan into a measured, dimensioned floor plan — with damage regions,
concealed-damage flags naming the rule that fired, a repair scope keyed to surfaces, and a
**90% interval on every number**.

Built for the Cozmo AI Applied AI case study. Start with
[`docs/compliance_matrix.md`](docs/compliance_matrix.md) for what is and is not done, then
[`docs/technical_report.md`](docs/technical_report.md).

## What each tier delivers today

| Tier | Input | State |
|---|---|---|
| **LiDAR** | Stray Scanner export folder | **Complete.** 6–43 s per capture, CPU only, no model, deterministic |
| **Video** | `.mov` from the Camera app | **Not built.** Detected, then a stated error |
| **Photo** | one folder per room, 2–8 stills | **Not built.** Detected, then a stated error |

Measured accuracy, against a synthetic room of exactly known size:
**ceiling height −3 mm, floor area +0.05%**, wall dimensions −40 mm on 4.00 m and −70 mm on
3.00 m. Repeatability on two real walks of one flat: footprint **0.8% apart**, room count
**4 vs 5** (this gate is not met — see [`docs/fix_loop.md`](docs/fix_loop.md)).

The device available for this work is an **iPhone 16 base, which has no LiDAR**, so the LiDAR
tier runs on the three captures Cozmo supplied and on ARKitScenes. Stated in full in
[`docs/device_matrix.md`](docs/device_matrix.md).

## Install and run — under 15 minutes on a clean machine

Needs Python 3.10–3.12. **No model weights and no network are required for the LiDAR tier.**

```bash
git clone <this repo> && cd scanplan
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q                                  # expect: 38 passed
```

On a CPU-only Linux machine, install PyTorch from the CPU index **first** if you plan to add
the model-dependent tiers later, or pip will pull ~2.5 GB of unusable CUDA libraries:

```bash
pip install "torch>=2.4,<2.10" "torchvision>=0.19,<0.25" --index-url https://download.pytorch.org/whl/cpu
```

### One command per capture

```bash
scanplan run path/to/StrayScannerExport
```

Writes to `out/<name>/`:

| File | What |
|---|---|
| `result.json` | everything, validated against [`schema/output.schema.json`](schema/output.schema.json) before it is written |
| `plan.svg` | the dimensioned plan |
| `summary.md` | room table with ranges, and what to be careful of |

Other commands:

```bash
scanplan inspect <capture>          # what the pipeline thinks it was handed
scanplan validate <result.json>     # check any result against the schema
scanplan run <capture> --no-drift   # the G-DRIFT on/off ablation
scanplan run <capture> --no-damage  # skip damage detection
```

## Design, in one paragraph

Three front-ends, one core. Each tier fills the same [`CaptureIR`](scanplan/ir.py); everything
downstream — geometry, error model, exports, benchmarks — sees only that. The tiers differ
almost entirely in **how metric scale is recovered**, so scale is an explicit field carrying a
value, a sigma and a *provenance*, rather than an assumption baked into each path. The LiDAR
path uses **no neural model**: the phone measures distance directly, and everything after is
plane fitting, rasterisation and least squares. That is what makes it fast, deterministic, and
unable to fail on a missing download during a live run.

## Reproduce every reported number

```bash
export COZMO_DATA=/path/to/captures     # then: ln -s "$COZMO_DATA" data/supplied
bash bench/reproduce.sh
```

It verifies the input checksums **first** — a benchmark over quietly damaged input produces
numbers that look reasonable and are wrong, which happened here once when an extraction
silently corrupted three PNGs while the archives themselves verified fine.

| Script | Produces |
|---|---|
| `bench/gates.py` | every gate current data can answer → `results/gates.md` |
| `bench/fix_loop_diagnosis.py` | the evidence behind the fix-loop declaration |
| `bench/arkitscenes_laser.py` | depth-bias calibration against FARO laser truth |
| `scripts/capture_manifest.py` | checksum the captures, and check them later |

## Honest limits

- **Two of three mandatory tiers are not built.** This is the largest gap.
- **No tape or laser truth exists for the captures the pipeline runs on**, so most gates read
  *not measured*. Absolute accuracy comes from synthetic geometry or from repeatability.
- **The device depth bias is an assumption**, 12 mm, labelled as such. The calibration
  benchmark currently returns NOT MEASURED rather than a number it cannot defend.
- **Room splitting is not repeatable** — 4 vs 5 rooms on two walks of one flat.
- **Damage class is shape-derived**, confidence ≤ 0.5. Naming a defect needs appearance.
- **Mirrors, glass and low light are not handled.**

Full list with reasons: [`docs/technical_report.md`](docs/technical_report.md) §7.

## Documents

| | |
|---|---|
| [`compliance_matrix.md`](docs/compliance_matrix.md) | requirement → file → artifact → status |
| [`technical_report.md`](docs/technical_report.md) | architecture, error budget, fix loop, failure modes |
| [`fix_loop_declaration.md`](docs/fix_loop_declaration.md) | committed **before** the fix |
| [`fix_loop.md`](docs/fix_loop.md) | outcome and post-mortem — the prediction was wrong |
| [`gates.md`](docs/gates.md) | every target, marked brief-derived or our decision |
| [`capture_protocol.md`](docs/capture_protocol.md) | one page, followable by a non-engineer |
| [`device_matrix.md`](docs/device_matrix.md) | which tier runs on which hardware |
| [`damage_rules.md`](docs/damage_rules.md) | the six concealed-damage rules |
