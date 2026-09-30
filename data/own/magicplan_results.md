# magicplan results — the incumbent's numbers

App: **magicplan 2026.38.0**, iPhone 16 (base, no LiDAR), **Manual-Scan → Corner Mode**.
Captured 2026-09-30. Exports in `data/own/magicplan/`: Sketch PDF, Report PDF, and a DXF.

Corner Mode is the only mode available without LiDAR; Auto-Scan and Wall Mode both require it.
magicplan's published accuracy without LiDAR is roughly 5–15 cm per wall.

## R1 — Bedroom (main room, open plan, L-shaped)

| Quantity | magicplan |
|---|---|
| Floor area | **13.25 m²** |
| Ceiling height | **2.83 m** |
| Perimeter | **13.41 m** |
| Left wall | 3.62 m |
| Right wall | 4.10 m |
| Bottom wall (total) | 3.44 m |
| Top-left segment | 1.78 m |
| Notch depth | 0.49 m |
| Top-right segment | 1.66 m |
| Bottom door width | 0.77 m |
| Upper-right door width | 0.90 m |

## R2 — Bathroom

| Quantity | magicplan |
|---|---|
| Floor area | **2.79 m²** |
| Ceiling height | **2.79 m** |
| Perimeter | **5.91 m** |

## From the DXF

`My New Project - Ground Floor.dxf`, AC1015, `$INSUNITS = 6` (metres). Layers: walls, doors,
windows, furnitures, texts. Three closed wall-band polylines, one per wall run, each drawn as
an outer and inner face joined at the ends — so **wall thickness is explicit at 0.25 m**, and
both the inside and outside face lengths are recoverable rather than inferred.

Bedroom wall-band segments, metres:

```
0.749, 0.488, 1.782, 3.614, 1.963, 0.250, 2.213, 4.114, 1.782, 0.488, 0.999, 0.250
```

These agree with the on-screen dimensions (1.78, 3.62, 1.96, 0.49, 4.10) to the millimetre,
so the plan view and the CAD export are consistent with each other.

Having the DXF matters: the comparison can be run on **coordinates** rather than on numbers
read off a picture, and magicplan's own wall-thickness convention is visible, so our inside-face
measurements can be compared against its inside faces rather than against an unknown reference.

## Note for the head-to-head write-up

Free tier permitted DXF, Sketch PDF and Report PDF export without payment.
