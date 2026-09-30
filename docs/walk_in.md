# Walk-in runbook

The defence is a cold run on a space nobody here has seen, with the examiners choosing the
tier and measuring the room with a laser while it runs. This page is what to do on the day.

## Before leaving

```bash
cd scanplan && source .venv/bin/activate
pytest -q                 # 38 passed
scanplan --version
```

Nothing else. **The LiDAR tier needs no weights and no network** — that is deliberate, and it
is why this page is short.

## If they choose LiDAR

1. They capture with **Stray Scanner**, following `docs/capture_protocol.md`.
2. Export the folder from the phone, copy it across.
3. ```bash
   scanplan run /path/to/export
   ```
4. Expect **6–43 s** depending on walk length. Read the room table straight off `summary.md`,
   or open `report`/`plan.svg` to show the plan.

## If they choose video or photo

Say so plainly: **those tiers are not built.** The pipeline will detect the tier correctly and
raise a stated error rather than pretending. Offer the LiDAR tier and point at
`docs/compliance_matrix.md` §1.2, which says the same thing in writing.

Do not improvise. A tier that produces a confident wrong plan is worth less than an honest
refusal, and the whole submission is built on that principle.

## What to say about the numbers

- Every value carries a **nominal 90% interval**. Quote the interval, not just the value.
- Ceiling height is the tightest quantity: **−3 mm** against synthetic truth.
- Wall dimensions read **slightly short by design** — floor area is what was measured, not what
  a fill could reach, so it under-reports rather than inventing. Expect roughly −1 to −2%.
- Room *count* may not match what a human would say. It under-splits. A merged pair still
  reports a correct combined area.
- The 12 mm inside every surface interval is an **unmeasured** bias allowance, not a result.

## If something goes wrong

| Symptom | Do this |
|---|---|
| `error: ... no floor found` | The capture never showed the floor. Ask for a re-walk with the floor sweep in `capture_protocol.md` §Tier 1 step 4 |
| `error: not a complete Stray Scanner export` | Wrong folder level — point at the one containing `odometry.csv` |
| A frame fails to decode | Already handled; it is skipped with a warning and the run continues |
| Anything unexpected | The CLI prints one line and exits non-zero, never a traceback. `SCANPLAN_TRACEBACK=1` gives the full trace for debugging |

## Questions to expect, and the short answers

**"Why no ML?"** The LiDAR tier does not need it — the phone measures distance directly. Models
would be required for video and photo, where a plain camera measures nothing and scale is
mathematically unobservable. Nothing that produces a *number* would use one.

**"Why is your room count wrong?"** It under-splits. `door_max_m` is one global number and rooms
are not one size. The fix loop targeted exactly this and moved it from 3-vs-6 to 4-vs-5 without
meeting the gate; `docs/fix_loop.md` says why.

**"Where is your ground truth?"** Synthetic geometry and repeatability. There is none for the
supplied captures — nobody here has stood in that property. The laser calibration against
ARKitScenes returns NOT MEASURED rather than a number it cannot defend.

**"Your intervals look wide."** They carry a 12 mm unmeasured bias allowance. Without it the
ceiling sigma computes to 0.1 mm, which is the standard error of 250,000 points and is
nonsense — averaging removes noise, not a systematic offset.
