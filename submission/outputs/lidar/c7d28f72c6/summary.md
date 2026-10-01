# c7d28f72c6 — lidar tier

5 rooms · footprint **49.65 m²** (46.38 to 52.91) · 52.56 s

Every value carries a nominal 90% interval. Values the sensor never saw are marked *not observed* and given deliberately wide ranges.

| Room | Floor area (m²) | Ceiling height (m) | Walls (m) | Openings (m) |
|---|---|---|---|---|
| R1 | 4.38 (4.09–4.67) | 3.09 (3.08–3.10) | 0.37 · 1.03 · 0.62 · 1.08 · 0.37 · 2.20 · 1.83 · 1.19 · 0.62 · 0.80 · 1.10 · 0.61 · 1.25 | 0.44 · 0.16 |
| R2 | 36.96 (34.53–39.39) | 3.09 (3.08–3.10) | 0.60 · 1.82 · 0.61 · 0.42 · 1.87 · 1.29 · 0.78 · 0.42 · 2.46 · 0.68 · 1.38 · 0.41 · 1.31 · 2.07 · 4.29 · 2.33 · 0.37 · 0.48 · 3.94 · 0.79 · 1.52 · 0.55 · 1.18 · 0.79 · 1.10 · 1.66 · 0.73 · 1.55 · 1.88 · 1.04 · 1.82 · 0.64 · 2.24 · 1.13 · 2.28 · 1.04 · 0.78 · 0.78 · 0.39 · 1.12 · 0.57 | 0.44 · 0.34 · 0.28 · 0.48 |
| R3 | 3.02 (2.82–3.22) | 3.09 (3.08–3.10) | 0.60 · 0.89 · 1.79 · 1.43 · 1.61 | 0.34 · 0.52 |
| R4 | 2.74 (2.56–2.92) | 3.09 (3.08–3.10) | 1.16 · 0.90 · 1.04 · 1.80 | 0.16 · 0.28 |
| R5 | 2.54 (2.38–2.71) | 3.09 (3.08–3.10) | 1.18 · 0.57 · 2.88 · 1.66 · 0.96 · 1.79 | 0.48 · 0.52 |

## What to be careful of

- **warning** — mirrors and glass are NOT detected. Two geometric tests were built and neither separates a reflection from ordinary geometry; 12.9% of points sit outside the floor envelope here, which is normal for ceilings and occluded floor. Geometry near any mirror in this capture is wrong and unflagged. The capture protocol asks the operator to approach mirrors at an angle
- **info** — rooms are split at doorway-width necks and under-split rather than over-split; a merged pair still reports a correct combined floor area, an invented room does not
