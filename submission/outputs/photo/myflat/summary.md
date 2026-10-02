# myflat — photo tier

2 rooms · footprint **8.13 m²** (2.24 to 14.01) · 18.97 s

Every value carries a nominal 90% interval. Values the sensor never saw are marked *not observed* and given deliberately wide ranges.

| Room | Floor area (m²) | Ceiling height (m) | Walls (m) | Openings (m) |
|---|---|---|---|---|
| R1 | 4.60 (1.27–7.93) | 2.10 (-2.42–6.63) | 2.21 · 2.08 · 2.21 · 2.08 | none found |
| R2 | 3.53 (0.97–6.08) | 2.55 (2.04–3.19) *(not seen)* | 2.17 · 1.63 · 2.17 · 1.63 | none found |

## What to be careful of

- **warning** — photo tier: 16 stills across 2 room folder(s). Depth is INFERRED, and there are NO camera poses -- each photo is levelled against the floor it can see but never located. Rooms are therefore NOT stitched: they are placed side by side, and the whole-property stitch gate fails by construction. An L-shaped room returns as its bounding box
- **error** — 2 room(s) are reported as separate rectangles, laid out side by side and joined to nothing. With no camera poses there is nothing in the input that says how the rooms relate, so the whole-property stitch gate fails by construction rather than by accident. Each room is the bounding box of what one view could see: an L-shaped room returns as a rectangle
