# c00a170fe1 — lidar tier

2 rooms · footprint **15.11 m²** (14.11 to 16.10) · 12.56 s

Every value carries a nominal 90% interval. Values the sensor never saw are marked *not observed* and given deliberately wide ranges.

| Room | Floor area (m²) | Ceiling height (m) | Walls (m) | Openings (m) |
|---|---|---|---|---|
| R1 | 10.79 (10.08–11.50) | 2.55 (2.04–3.19) *(not seen)* | 0.64 · 0.67 · 0.76 · 1.86 · 1.35 · 0.66 · 1.03 · 1.49 · 5.75 · 1.15 · 0.43 · 1.24 · 0.67 · 1.32 | 0.32 |
| R2 | 4.32 (4.03–4.60) | 2.55 (2.04–3.19) *(not seen)* | 1.26 · 1.10 · 3.28 · 1.84 · 1.15 · 0.67 · 1.76 | 0.32 |

## What to be careful of

- **warning** — the walk did not return to its start (3.18 m apart); drift correction has no loop to close, so accumulated error cannot be removed
- **warning** — mirrors and glass are NOT detected. Two geometric tests were built and neither separates a reflection from ordinary geometry; 10.9% of points sit outside the floor envelope here, which is normal for ceilings and occluded floor. Geometry near any mirror in this capture is wrong and unflagged. The capture protocol asks the operator to approach mirrors at an angle
- **warning** — floor is missing beneath 40% of the path the camera actually walked, which is the signature of a wet or glossy surface scattering the beam away. Floor area is under-reported there
- **warning** — the ceiling was never seen; ceiling heights are population typicals with wide intervals, flagged observed=false
- **info** — rooms are split at doorway-width necks and under-split rather than over-split; a merged pair still reports a correct combined floor area, an invented room does not
