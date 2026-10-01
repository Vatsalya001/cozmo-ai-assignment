# c00a170fe1 — video tier

2 rooms · footprint **24.13 m²** (6.67 to 41.60) · 116.32 s

Every value carries a nominal 90% interval. Values the sensor never saw are marked *not observed* and given deliberately wide ranges.

| Room | Floor area (m²) | Ceiling height (m) | Walls (m) | Openings (m) |
|---|---|---|---|---|
| R1 | 8.97 (2.48–15.46) | 2.55 (2.04–3.19) *(not seen)* | 1.03 · 0.48 · 1.17 · 0.58 · 1.06 · 1.52 · 1.79 · 1.78 · 1.61 · 1.12 · 1.40 · 1.26 · 1.87 | 0.17 |
| R2 | 15.17 (4.19–26.15) | 2.55 (2.04–3.19) *(not seen)* | 0.50 · 0.95 · 0.90 · 0.45 · 1.10 · 0.90 · 1.52 · 1.43 · 0.89 · 0.58 · 0.93 · 3.80 · 0.93 · 2.32 | 0.17 |

## What to be careful of

- **warning** — video tier: depth for 119 keyframes is INFERRED by Depth-Anything-V2-Metric-Indoor-Small-hf, not measured. Scale is unobservable from monocular images, so it comes from the model's metric training rather than from this room. Intervals are widened accordingly
- **warning** — mirrors and glass are NOT detected. Two geometric tests were built and neither separates a reflection from ordinary geometry; 1.9% of points sit outside the floor envelope here, which is normal for ceilings and occluded floor. Geometry near any mirror in this capture is wrong and unflagged. The capture protocol asks the operator to approach mirrors at an angle
- **warning** — floor is missing beneath 55% of the path the camera actually walked, which is the signature of a wet or glossy surface scattering the beam away. Floor area is under-reported there
- **warning** — the ceiling was never seen; ceiling heights are population typicals with wide intervals, flagged observed=false
- **info** — rooms are split at doorway-width necks and under-split rather than over-split; a merged pair still reports a correct combined floor area, an invented room does not
