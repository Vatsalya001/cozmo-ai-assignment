# 1a8384c3f6 — lidar tier

5 rooms · footprint **48.04 m²** (44.88 to 51.20) · 31.14 s

Every value carries a nominal 90% interval. Values the sensor never saw are marked *not observed* and given deliberately wide ranges.

| Room | Floor area (m²) | Ceiling height (m) | Walls (m) | Openings (m) |
|---|---|---|---|---|
| R1 | 3.28 (3.07–3.50) | 2.55 (2.04–3.19) *(not seen)* | 0.67 · 0.52 · 0.80 · 1.85 · 0.54 · 0.70 · 1.19 · 1.52 | 0.22 · 0.34 |
| R2 | 18.26 (17.06–19.47) | 2.55 (2.04–3.19) *(not seen)* | 2.19 · 1.60 · 1.84 · 1.71 · 3.48 · 0.88 · 0.67 · 3.28 · 1.89 · 2.01 · 0.82 · 2.19 · 1.26 · 0.95 · 0.46 | 0.22 · 0.22 · 0.20 · 0.20 |
| R3 | 23.22 (21.69–24.74) | 2.55 (2.04–3.19) *(not seen)* | 4.32 · 3.41 · 1.52 · 0.48 · 1.27 · 0.58 · 1.24 · 0.94 · 0.64 · 2.84 · 0.38 · 1.00 · 2.68 · 0.62 · 2.94 · 0.94 · 1.02 · 1.23 · 0.78 · 2.56 · 1.99 · 1.23 · 1.29 · 1.21 · 1.69 · 0.93 · 0.68 · 1.03 · 2.07 · 0.52 · 1.03 · 1.06 · 0.55 · 0.56 | 0.34 · 0.22 · 0.44 |
| R4 | 1.43 (1.34–1.52) | 2.55 (2.04–3.19) *(not seen)* | 0.93 · 0.56 · 0.79 · 1.19 · 0.82 · 0.76 | 0.20 |
| R5 | 1.85 (1.73–1.97) | 2.55 (2.04–3.19) *(not seen)* | 0.99 · 1.43 · 1.29 · 0.68 | 0.20 · 0.44 |

## What to be careful of

- **warning** — tracking relocalised 2 time(s) (largest 31 cm); geometry either side of a jump may not line up
- **warning** — mirrors and glass are NOT detected. Two geometric tests were built and neither separates a reflection from ordinary geometry; 9.5% of points sit outside the floor envelope here, which is normal for ceilings and occluded floor. Geometry near any mirror in this capture is wrong and unflagged. The capture protocol asks the operator to approach mirrors at an angle
- **warning** — the ceiling was never seen; ceiling heights are population typicals with wide intervals, flagged observed=false
- **info** — rooms are split at doorway-width necks and under-split rather than over-split; a merged pair still reports a correct combined floor area, an invented room does not
