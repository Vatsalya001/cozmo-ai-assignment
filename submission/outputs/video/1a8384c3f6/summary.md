# 1a8384c3f6 — video tier

1 rooms · footprint **35.20 m²** (9.72 to 60.68) · 102.87 s

Every value carries a nominal 90% interval. Values the sensor never saw are marked *not observed* and given deliberately wide ranges.

| Room | Floor area (m²) | Ceiling height (m) | Walls (m) | Openings (m) |
|---|---|---|---|---|
| R1 | 35.20 (9.72–60.68) | 2.55 (2.04–3.19) *(not seen)* | 2.27 · 0.56 · 1.23 · 1.03 · 0.54 · 1.28 · 0.91 · 0.78 · 1.08 · 0.44 · 1.11 · 1.11 · 1.81 · 0.62 · 1.50 · 1.37 · 0.48 · 1.61 · 0.65 · 0.69 · 0.98 · 0.85 · 0.82 · 0.95 · 0.86 · 0.86 · 1.21 · 2.46 · 2.39 · 1.37 · 0.80 · 0.88 · 0.39 · 0.79 · 0.94 · 0.88 · 1.24 · 0.69 · 1.03 · 0.51 · 1.11 · 0.92 · 0.78 · 0.73 · 0.77 · 0.80 · 0.72 · 1.18 | none found |

## What to be careful of

- **warning** — video tier: depth for 119 keyframes is INFERRED by Depth-Anything-V2-Metric-Indoor-Small-hf, not measured. Scale is unobservable from monocular images, so it comes from the model's metric training rather than from this room. Intervals are widened accordingly
- **warning** — mirrors and glass are NOT detected. Two geometric tests were built and neither separates a reflection from ordinary geometry; 3.8% of points sit outside the floor envelope here, which is normal for ceilings and occluded floor. Geometry near any mirror in this capture is wrong and unflagged. The capture protocol asks the operator to approach mirrors at an angle
- **warning** — floor is missing beneath 42% of the path the camera actually walked, which is the signature of a wet or glossy surface scattering the beam away. Floor area is under-reported there
- **warning** — the ceiling was never seen; ceiling heights are population typicals with wide intervals, flagged observed=false
- **info** — rooms are split at doorway-width necks and under-split rather than over-split; a merged pair still reports a correct combined floor area, an invented room does not
