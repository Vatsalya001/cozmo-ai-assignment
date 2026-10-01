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
| **LiDAR** | complete | 6–53 s per capture, CPU only | Synthetic room of exactly known size: ceiling height **−3 mm**, floor area **+0.05%**, wall dimensions **−40 mm on 4.00 m** and **−70 mm on 3.00 m**. Repeatability on two real walks of one flat: footprint **0.7% apart**, room count **4 vs 5** |
| **Video** | built, gate not met | ~95 s per capture | Footprint **62% and 26%** from the LiDAR reference on the same captures; produced a plan on 2 of 3, failed outright on the third. Interval widening **×11, measured** from that error — it contains the reference 2/2 |
| **Photo** | built, stitch fails by construction | ~10 s | Room boxes from unposed stills, laid out side by side and joined to nothing. No reference exists for these folders, so no accuracy number is claimed |

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
| Video and photo tiers | would need ~3 GB of model weights and, on this CPU-only machine, minutes per capture rather than seconds |

## Accuracy caveats worth stating

- **No tape or laser ground truth exists for the captures the pipeline runs on.** The supplied
  captures are of a property none of us has stood in. Every absolute accuracy number above
  comes either from synthetic geometry or from repeatability between two walks.
- **The device depth bias is unmeasured.** Surface heights carry a 12 mm allowance labelled as
  an assumption. `bench/arkitscenes_laser.py` attempts to measure it against FARO laser truth
  and currently reports NOT MEASURED, because both downloaded scans are multi-level walks with
  no single floor.
- **Room splitting is not repeatable.** Two walks of the same flat give 4 and 5 rooms. Floor
  area is stable at 0.8%; its division into rooms is not.
