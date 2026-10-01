# Device matrix

Which tier runs on which hardware, and what accuracy each honestly delivers.

## Capture hardware

| Tier | Minimum device | Capture app | Why |
|---|---|---|---|
| **LiDAR** | iPhone 12 Pro / iPad Pro or newer | Stray Scanner | ARKit exposes `sceneDepth` only on LiDAR-equipped devices. Standard iPhones have no depth sensor at any iOS version |
| **Video** | iPhone 15 or newer | stock Camera app, 1080p/30, HDR off | Per the brief |
| **Photo** | iPhone 15 or newer | stock Camera app, 2–8 stills per room | Per the brief |

**The device used for this submission is an iPhone 16 (base), which has no LiDAR.** The LiDAR
tier therefore runs on the three captures Cozmo supplied and on ARKitScenes, not on captures
of our own. This is stated wherever it affects a result rather than left to be inferred.

## What each tier delivers

| Tier | State | Runtime | Measured accuracy |
|---|---|---|---|
| **LiDAR** | complete | roughly 10–50 s per capture, CPU only | Synthetic room of exactly known size: ceiling height **−3.3 mm**, floor height **+1.8 mm**, floor area **−3.03%**, wall dimensions **−60 mm on 4.00 m** and **−120 mm on 3.00 m**. Repeatability on two real walks of one flat: room count **5 vs 5 (met)**, footprint **3.2% apart (not met)** |
| **Video** | built, gate not met | ~110 s per capture | Footprint **+59.7% and −26.7%** from the LiDAR reference on the same captures; produced a plan on 2 of 3, failed outright on the third with a stated `no floor found`. Interval widening **×11, measured** from that error — it contains the reference 2/2 |
| **Photo** | built, stitch fails by construction | ~13 s | Room boxes from unposed stills, laid out side by side and joined to nothing. No reference exists for these folders, so no accuracy number is claimed |

Both lower tiers infer depth with a metric monocular model, because a plain camera measures
no distance and scale is mathematically unobservable from monocular images. That is inference
filling in for a sensor, and it is why their intervals widen to **×11** — a factor measured
from the error against the LiDAR reference, not chosen. The video tier also takes its poses
from the capture app's ARKit track, which an iPhone 15 non-Pro produces without any depth
sensor; the photo tier has no poses at all, which is why it cannot stitch.

## Processing hardware

| | |
|---|---|
| Developed and benchmarked on | Linux, CPU only, no GPU |
| LiDAR tier | needs **no model and no weights** — pure geometry. This is why it is fast and deterministic, and why it cannot fail on a missing download during a live run |
| Video and photo tiers | need torch plus a **95 MB** checkpoint (`Depth-Anything-V2-Metric-Indoor-Small-hf`) and, on this CPU-only machine, ~2 minutes per capture rather than seconds. Installed as an explicit extra: `pip install -e ".[dev,models]"` |

## Accuracy caveats worth stating

- **No tape or laser ground truth exists for the captures the pipeline runs on.** The supplied
  captures are of a property none of us has stood in. Every absolute accuracy number above
  comes either from synthetic geometry or from repeatability between two walks.
- **The device depth bias is MEASURED**, and this is the one number here that rests on a
  surveying instrument. `bench/depth_bias.py` compares device depth against FARO-derived laser
  depth **per pixel on the same frames**: the device reads **18.0 mm short**, pooled over
  4.79 million pixels across 8 ARKitScenes scans. It is corrected at ingest. Per-scan medians
  span 13 mm, so one correction cannot fit every scan, and the **4.1 mm standard deviation**
  that survives is carried on every surface height.
- **Storey height against truth is still NOT MEASURED.** Three approaches failed for one
  reason: ARKitScenes venues are overwhelmingly multi-storey, and a storey height needs a
  capture with exactly one floor and one ceiling. `bench/ceiling_vs_laser.py` documents all
  three rather than dropping the gate.
- **Footprint repeatability is 3.2% and not met**, while room count (5 vs 5) is met. Applying
  the depth-bias correction flipped which of the two passes — before it, room count failed at
  4-vs-5 and footprint passed at 0.7%. Two gates that trade places under an 18 mm sensor
  correction were never measuring independent properties.
