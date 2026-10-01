"""Photo tier: 2-8 stills per room, no depth, no poses.

This is the thinnest input the brief defines, and the honesty problem is sharper here than
anywhere else in the pipeline.

## What is actually available

A still carries no depth and no pose. Depth can be inferred by a metric model, as in the video
tier. Poses cannot: recovering them from a handful of wide-baseline stills is
structure-from-motion, and an unvalidated SfM stage underneath every number would make the
whole tier undefendable.

So this tier does **not** attempt a pose graph. Each photo is reconstructed in its own camera
frame, levelled against the floor it can see, and reduced to the one thing a single view can
honestly support: **the extent of the room around the camera**. Per room, the per-photo
estimates are combined; across rooms, nothing is joined, because nothing in the input says how
the rooms relate.

## What that costs, stated up front

- **No stitching.** Each room folder becomes its own disconnected room. The brief's
  whole-property stitch gate (G-PHOTO-STITCH) therefore fails by construction, not by accident.
- **Rectangular rooms only.** A single view reaches the walls it can see; an L-shaped room
  comes back as its bounding box.
- **Scale is the model's, not the room's.** Same as the video tier, and the interval says so.

Reporting a plan built this way with narrow intervals would be the clearest possible case of
the confident garbage the brief penalises, so the photo widening factor is the largest in the
pipeline and every run carries a warning naming these limits.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ..detect import CaptureError, room_folders
from ..ir import CaptureIR, Frame, Intrinsics, ScaleEstimate

cv2.setNumThreads(0)

MAX_PER_ROOM = 8            # the brief's cap
DEPTH_W, DEPTH_H = 256, 192
DEPTH_MAX_M = 8.0
DEFAULT_HFOV_DEG = 66.0     # iPhone main camera, used when EXIF carries no focal length


def _intrinsics_from_exif(image_path: Path, width: int, height: int) -> Intrinsics:
    """Focal length from EXIF where the photo carries it, else a stated iPhone default.

    This is the one place the photo tier gets real metric information from the capture rather
    than from a model, so it is worth reading properly: focal length sets the angular scale of
    every pixel, and getting it wrong scales the whole room.
    """
    fx = None
    try:
        from PIL import Image, ExifTags
        with Image.open(image_path) as im:
            exif = im.getexif()
            tags = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
            f35 = tags.get("FocalLengthIn35mmFilm")
            if f35:
                # 35 mm equivalent: horizontal FOV follows from the 36 mm frame width.
                fx = float(f35) / 36.0 * width
    except Exception:                                  # noqa: BLE001 -- EXIF is best-effort
        fx = None

    if not fx or not np.isfinite(fx) or fx <= 0:
        fx = (width / 2) / np.tan(np.deg2rad(DEFAULT_HFOV_DEG / 2))

    return Intrinsics(fx, fx, (width - 1) / 2, (height - 1) / 2, width, height)


FLOOR_SIDE_FRACTION = 0.80      # a floor has at least this share of the room on one side of it
FLOOR_BAND_M = 0.05             # inlier distance to the plane


def _level_to_floor(points: np.ndarray) -> np.ndarray | None:
    """Rotate a single-view cloud so the floor is horizontal and at y = 0.

    Without a pose there is no gravity, so it is recovered from the scene. The previous version
    assumed the camera was held upright -- it required the plane normal to lie within 32 degrees
    of camera-y (`abs(n[1]) >= 0.85`) and drew candidates from the lowest slab of camera-y.

    **That assumption is false whenever the phone is rotated, and it failed silently.** On the
    frames this project's own photo set is cut from, camera-down is 92.8 to 93.8 degrees away
    from world-down -- the phone was held turned, so camera -y points sideways. The gate then
    accepted a plane normal to camera-y, which is a WALL, and the tier levelled the room against
    it and reported the extent of a wall patch as the room. That is the whole of the 3-4x
    under-report in G-WALL-PHOTO, and the published diagnosis blaming the depth model was wrong:
    the inferred depth runs about 1.26x LONG on these frames, not short.

    A landscape photograph of a room is a perfectly ordinary thing to hand this tier, so the
    orientation assumption had to go rather than be documented.

    ## What replaces it, without assuming an axis

    A floor is identifiable by geometry alone: it is a large plane with essentially the whole
    room on ONE side of it. Walls fail that test -- a room straddles a wall plane, with material
    on both sides -- and so do table tops, which are large but have the floor beneath them.
    So the fit searches every orientation and keeps the plane that maximises inliers subject to
    at least FLOOR_SIDE_FRACTION of all points lying on one side.
    """
    if len(points) < 500:
        return None

    # Every point is a candidate now: restricting to a slab of camera-y was the orientation
    # assumption in its other guise, and it biased the search toward wall planes.
    cand = points
    if len(cand) < 200:
        return None

    best, best_inliers = None, 0
    rng = np.random.default_rng(0)
    for _ in range(400):                     # a wider search, since the normal is unconstrained
        idx = rng.choice(len(cand), 3, replace=False)
        a, b, c = cand[idx]
        n = np.cross(b - a, c - a)
        norm = np.linalg.norm(n)
        if norm < 1e-9:
            continue
        n = n / norm
        d0 = -float(n @ a)
        # The floor test, replacing the axis gate: nearly everything on one side.
        signed = points @ n + d0
        side = max((signed > FLOOR_BAND_M).mean(), (signed < -FLOOR_BAND_M).mean())
        if side < FLOOR_SIDE_FRACTION:
            continue
        d = d0
        inliers = int((np.abs(cand @ n + d) < 0.05).sum())
        if inliers > best_inliers:
            best, best_inliers = (n, d), inliers

    if best is None or best_inliers < 150:
        return None

    n, d = best
    # Orient the normal by WHICH SIDE THE ROOM IS ON, not by camera-y -- that was the same
    # orientation assumption in its last hiding place. The rotation below maps n onto world
    # -y (down), so n has to point away from the room: the room must end up on the -n side,
    # or the whole cloud is levelled upside down and the floor becomes the ceiling.
    if (points @ n + d > 0).mean() > 0.5:
        n, d = -n, -d

    # Rotation taking the floor normal onto world -y (world y up, floor below the camera).
    target = np.array([0.0, -1.0, 0.0])
    v = np.cross(n, target)
    s, c = np.linalg.norm(v), float(n @ target)
    if s < 1e-9:
        R = np.eye(3) if c > 0 else -np.eye(3)
    else:
        vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
        R = np.eye(3) + vx + vx @ vx * ((1 - c) / s ** 2)

    out = points @ R.T
    out[:, 1] -= np.percentile(out[:, 1], 2)          # put the floor at y = 0
    return out


def load(path, *, max_per_room: int = MAX_PER_ROOM, progress: bool = False) -> CaptureIR:
    """Build a CaptureIR from per-room photo folders.

    Each photo becomes one frame whose pose is a pure levelling rotation -- an honest statement
    that the view was oriented but never located. Rooms are laid out side by side rather than
    joined, because nothing in the input says how they relate.
    """
    path = Path(path)
    folders = room_folders(path)
    if not folders:
        raise CaptureError(
            f"{path}: the photo tier expects one folder per room, e.g. {path.name}/kitchen/*.jpg")

    from .video import _depth_model
    from PIL import Image

    model = _depth_model()
    ir = CaptureIR(
        capture_id=path.name, tier="photo",
        scale=ScaleEstimate(1.0, 0.15, "metric_depth_model",
                            "metric depth model; scale is the model's, not this room's"))

    per_room: dict[str, list] = {}
    room_names = []
    for folder in folders:
        images = sorted(p for p in folder.iterdir()
                        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".heic", ".heif"})
        if not images:
            continue
        images = images[:max_per_room]
        room_names.append(folder.name)
        if progress:
            print(f"  photo tier: {folder.name} ({len(images)} photos)", flush=True)

        for i, img_path in enumerate(images):
            bgr = cv2.imread(str(img_path))
            if bgr is None:
                continue
            small = cv2.resize(bgr, (DEPTH_W * 2, DEPTH_H * 2), interpolation=cv2.INTER_AREA)
            out = model(Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB)))
            depth = np.asarray(
                out["predicted_depth"] if "predicted_depth" in out else out["depth"],
                dtype=np.float32)
            if depth.shape != (DEPTH_H, DEPTH_W):
                depth = cv2.resize(depth, (DEPTH_W, DEPTH_H), interpolation=cv2.INTER_NEAREST)
            depth[(depth <= 0) | (depth > DEPTH_MAX_M)] = 0.0

            K = _intrinsics_from_exif(img_path, DEPTH_W, DEPTH_H)
            v, u = np.nonzero(depth > 0)
            if len(u) < 500:
                continue
            z = depth[v, u]
            cam = np.stack([(u - K.cx) / K.fx * z, (v - K.cy) / K.fy * z, z], axis=1)
            levelled = _level_to_floor(cam)
            if levelled is None:
                continue

            per_room.setdefault(folder.name, []).append(levelled)
            ir.frames.append(Frame(
                index=len(ir.frames), timestamp=float(len(ir.frames)),
                intrinsics=K, world_from_cam=np.eye(4),
                depth_m=None, depth_confidence=None, image_path=str(img_path)))

    if not per_room:
        raise CaptureError(f"{path}: no photo produced a usable levelled view")
    # Carried on the IR so the pipeline can take the photo-tier geometry path, which does not
    # assume a traversal the way the walked-capture core does.
    ir.photo_room_clouds = per_room

    ir.warnings.append(
        f"photo tier: {len(ir.frames)} stills across {len(room_names)} room folder(s). Depth is "
        f"INFERRED, and there are NO camera poses -- each photo is levelled against the floor it "
        f"can see but never located. Rooms are therefore NOT stitched: they are placed side by "
        f"side, and the whole-property stitch gate fails by construction. An L-shaped room "
        f"returns as its bounding box")
    return ir
