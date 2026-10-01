# scanplan

Turn an iPhone capture — LiDAR scan, video walkthrough, or a folder of photos — into a
measured, dimensioned floor plan — with damage regions,
concealed-damage flags naming the rule that fired, a repair scope keyed to surfaces, and a
**90% interval on every number**.

Built for the Cozmo AI Applied AI case study. Start with
[`docs/compliance_matrix.md`](docs/compliance_matrix.md) for what is and is not done, then
[`docs/technical_report.md`](docs/technical_report.md).

## What each tier delivers today

| Tier | Input | State |
|---|---|---|
| **LiDAR** | Stray Scanner export folder | **Complete.** roughly 10–50 s per capture, CPU only, **no model**, deterministic |
| **Video** | `rgb.mp4` + the capture app's pose track | **Built, gate not met.** ~110 s. **+59.7%** and **−26.7%** from the LiDAR reference; failed on 1 of 3 captures |
| **Photo** | one folder per room, 2–8 stills | **Built, gate not met.** ~13 s. Room boxes from unposed stills; **does not stitch, by construction** |

Measured accuracy, against a synthetic room of exactly known size:
**ceiling height −3.3 mm**, floor height **+1.8 mm**, floor area **−3.03%**, wall dimensions
−60 mm on 4.00 m and −120 mm on 3.00 m. Repeatability on two real walks of one flat: room count
**5 vs 5 (met)**, footprint **3.2% apart (not met)** — and the measured depth-bias correction
is what flipped which of those two passes, see [`docs/fix_loop.md`](docs/fix_loop.md) §10.

The area figure reads worse than it used to and is more trustworthy for it: **+0.05%** was two
errors cancelling, a 12 mm over-correction offsetting the amount coverage-based area
under-reports. Fixing the sensor model made the headline number look worse and made it true.

The device available for this work is an **iPhone 16 base, which has no LiDAR**, so the LiDAR
tier runs on the three captures Cozmo supplied and on ARKitScenes. Stated in full in
[`docs/device_matrix.md`](docs/device_matrix.md).

## Install and run — under 15 minutes on a clean machine

Needs Python 3.10–3.12. **No model weights and no network are required for the LiDAR tier.**

```bash
git clone https://github.com/Vatsalya001/cozmo-ai-assignment.git && cd cozmo-ai-assignment
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q                                  # expect: 77 passed
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
unable to fail on a missing download during a live run. The video and photo tiers **do** use
one — `depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf` — because scale is
mathematically unobservable from a single camera, and it is an explicit install extra so the
LiDAR tier's offline guarantee survives.

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
| `bench/depth_bias.py` | **the depth-bias calibration: −18.0 mm per-pixel against FARO laser truth**, 4.79 M pixels over 8 scans |
| `bench/video_vs_lidar.py` | the video tier against the LiDAR reference, and the interval calibration |
| `bench/photo_tier.py` | photo-tier room boxes and stitch grouping (builds its own input) |
| `bench/head_to_head.py` | magicplan comparison, dimension by dimension |
| `bench/fix_loop_diagnosis.py` | the evidence behind the fix-loop declaration, through `pipeline.run` |
| `bench/arkitscenes_laser.py` | storey-height calibration — reports **NOT MEASURED**, and the header says why |
| `bench/ceiling_vs_laser.py` | the second attempt at G-CEIL — also **NOT MEASURED**, all three approaches documented |
| `bench/clean_clone_check.sh` | **clone, install, regenerate, diff** — reproduction from scratch |
| `scripts/capture_manifest.py` | checksum the captures, and check them later |
| `scripts/build_photoset.py` | the photo-tier input, at fixed frame indices |
| `scripts/sync_compliance_matrix.py` | writes the matrix gate table from `gates.json` |

Two of these report **NOT MEASURED** and are kept anyway. A gate that was attempted and cannot
be answered is a different thing from a gate nobody tried, and the difference is only visible if
the attempt is still in the repo.

### Reproduction from a clean clone

```bash
bash bench/clean_clone_check.sh                 # no weights, no network
bash bench/clean_clone_check.sh --with-models   # also the two model tiers
```

Clones the repo, installs from scratch, runs the tests, regenerates the benchmarks and diffs
committed against regenerated. **With `--with-models`, 7 of 11 result files come back
byte-identical and the other 4 are named with the reason each cannot** — three are historical
snapshots of code states that no longer exist, one is wall-clock. It reports what it did *not*
regenerate rather than counting files it merely copied. It has caught four real defects.

## Honest limits

- **The video and photo tiers miss their accuracy gates by a wide margin**, and the video tier failed outright on one of three captures. Their intervals are widened ×11 from measured error so they do not overclaim.
- **No tape or laser truth exists for the captures the pipeline runs on**, so most gates read
  *not measured*. Absolute accuracy comes from synthetic geometry or from repeatability.
- **Footprint repeatability is 3.2% and not met** on two walks of one flat, while room count
  (5 vs 5) is met. The two gates traded places when the depth-bias correction landed, which
  says they were never measuring independent properties.
- **Storey height is NOT MEASURED against truth.** Three approaches were tried and all fail for
  one reason: ARKitScenes venues are overwhelmingly multi-storey. Written up in
  `bench/ceiling_vs_laser.py` rather than quietly dropped.
- **Damage class is shape-derived**, confidence ≤ 0.5. Naming a defect needs appearance.
- **Mirrors and glass are not detected.** Two geometric tests were built and neither separates
  a reflection from ordinary geometry, so the flag is disabled and every run says so rather
  than shipping a detector that fires on every capture. Wet floors and low light *are* detected.

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
