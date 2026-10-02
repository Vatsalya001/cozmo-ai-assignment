"""Read HouseLayout3D into storeys of room polygons and a door graph.

HouseLayout3D ships *buildings*, not captures, and it does not ship rooms either. What it
ships is one planar polygon per structural entity -- a wall, a floor patch, a ceiling patch --
with no class label, plus a flat list of door rectangles with no room membership. Everything
this module produces is therefore derived, and the derivation is worth stating because the
whole point of using the dataset is that the truth must not come from our side:

  room polygon   a floor-facing horizontal entity. The meshes are consistently wound with
                 normals pointing into the room, so a horizontal entity whose normal is +z is
                 a floor and one whose normal is -z is a ceiling. That is the dataset's own
                 orientation, not a guess about which is which.
  storey         a cluster of floor entities within half a metre in z. A 2D top-down plan is
                 one storey by construction; stair-linked rooms on different storeys cannot
                 appear in the same label image, so they cannot be in the same graph.
  room vs. not   a floor entity of at least ROOM_MIN_AREA_M2 -- *our* constant, the same one
                 scanplan already uses to drop a region that is too small to call a room.
                 Smaller floor patches are kept as walkable floor but are not rooms; nearly
                 all of them are the ~0.1 m2 reveal under a doorway.
  door edge      the pair of room polygons found by stepping off the door rectangle along its
                 annotated normal, in both directions, until a room polygon is hit. Doors that
                 find a room on only one side are exterior doors and are reported separately.

Nothing here reads scanplan. The truth side and the measured side share only the dataset.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from matplotlib.path import Path as MplPath

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "external" / "houselayout3d"

HORIZONTAL_NZ = 0.95        # |n_z| above this is a floor or a ceiling, not a wall or a ramp
STOREY_GAP_M = 1.00         # a gap in floor height larger than this is a different storey. Set
                            # from the data, not tuned: within these 16 buildings every gap
                            # between room-sized floor patches is either under 0.8 m (a step or
                            # a split level, still one top-down plan) or over 1.8 m (a storey).
DOOR_SILL_TOL_M = 0.50      # how far a door sill may sit from its storey's median floor height
PROBE_MAX_M = 1.20          # how far to step off a door before giving up on finding a room
PROBE_STEP_M = 0.02


def _read_ply(path: Path) -> tuple[np.ndarray, list[list[int]]]:
    """Vertices and faces of one Open3D-written binary little-endian ply."""
    blob = path.read_bytes()
    end = blob.index(b"end_header\n") + len(b"end_header\n")
    header = blob[:end].decode()
    counts = {}
    for line in header.splitlines():
        if line.startswith("element "):
            _, name, n = line.split()
            counts[name] = int(n)
    dtype = np.dtype([("x", "<f8"), ("y", "<f8"), ("z", "<f8"),
                      ("r", "u1"), ("g", "u1"), ("b", "u1")])
    nv = counts["vertex"]
    verts = np.frombuffer(blob, dtype=dtype, count=nv, offset=end)
    xyz = np.stack([verts["x"], verts["y"], verts["z"]], axis=1).astype(np.float64)

    off = end + dtype.itemsize * nv
    faces = []
    for _ in range(counts.get("face", 0)):
        k = blob[off]
        off += 1
        faces.append(np.frombuffer(blob, dtype="<u4", count=k, offset=off).tolist())
        off += 4 * k
    return xyz, faces


def _area_normal(xyz: np.ndarray, faces: list[list[int]]) -> np.ndarray:
    """Sum of triangle normals, so its length is twice the area and its sign is the winding."""
    total = np.zeros(3)
    for face in faces:
        for a, b in zip(face[1:-1], face[2:]):
            total += np.cross(xyz[a] - xyz[face[0]], xyz[b] - xyz[face[0]])
    return total


def _boundary_ring(xyz: np.ndarray, faces: list[list[int]]) -> np.ndarray | None:
    """The outline of a triangulated planar patch: edges used by exactly one face, walked.

    Returns the longest ring if the patch has holes or is pinched; None if no ring closes.
    """
    use: Counter = Counter()
    for face in faces:
        for a, b in zip(face, face[1:] + face[:1]):
            use[(min(a, b), max(a, b))] += 1
    adj: dict[int, list[int]] = defaultdict(list)
    for (a, b), n in use.items():
        if n == 1:
            adj[a].append(b)
            adj[b].append(a)
    if not adj:
        return None

    rings, seen = [], set()
    for start in sorted(adj):
        if start in seen:
            continue
        ring, prev, cur = [start], None, start
        seen.add(start)
        while True:
            nxt = next((v for v in sorted(adj[cur]) if v != prev and v not in seen), None)
            if nxt is None:
                if start in adj[cur] and len(ring) >= 3:
                    rings.append(ring)
                break
            ring.append(nxt)
            seen.add(nxt)
            prev, cur = cur, nxt
    if not rings:
        return None
    best = max(rings, key=lambda r: abs(_shoelace(xyz[r][:, :2])))
    return xyz[best]


def _shoelace(poly_xy: np.ndarray) -> float:
    x, y = poly_xy[:, 0], poly_xy[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


@dataclass
class FloorPatch:
    entity: int
    polygon_xy: np.ndarray      # (n, 2) metres, in the dataset's own horizontal frame
    z: float
    area_m2: float

    def contains(self, pts_xy: np.ndarray) -> np.ndarray:
        return MplPath(self.polygon_xy).contains_points(np.atleast_2d(pts_xy))


@dataclass
class Door:
    centre_xy: np.ndarray
    normal_xy: np.ndarray
    width_m: float
    bottom_z: float


@dataclass
class Storey:
    scene: str
    index: int
    z: float
    rooms: list[FloorPatch]         # patches big enough to be rooms, id = position in this list
    connectors: list[FloorPatch]    # walkable floor too small to be a room (door reveals)
    doors: list[Door]
    edges: set[tuple[int, int]]     # room-index pairs a door joins, 0-based, sorted
    exterior_doors: int             # doors that found a room on one side only
    unplaced_doors: int             # doors that found a room on neither side
    same_room_doors: int            # doors with the same room both sides: not split in the
                                    # annotation, so they join nothing it can be scored against


def scenes() -> list[str]:
    root = DATA / "structures" / "layouts_split_by_entity"
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def floor_patches(scene: str) -> list[FloorPatch]:
    """Every floor-facing horizontal patch in the building, as a polygon in metres."""
    out = []
    root = DATA / "structures" / "layouts_split_by_entity" / scene
    for path in sorted(root.glob("*.ply"), key=lambda p: int(p.stem)):
        xyz, faces = _read_ply(path)
        if len(faces) == 0 or len(xyz) < 3:
            continue
        nrm = _area_normal(xyz, faces)
        twice_area = float(np.linalg.norm(nrm))
        if twice_area < 1e-9:
            continue
        unit = nrm / twice_area
        if unit[2] < HORIZONTAL_NZ:       # +z: horizontal and facing up into the room
            continue
        ring = _boundary_ring(xyz, faces)
        if ring is None:
            continue
        out.append(FloorPatch(entity=int(path.stem), polygon_xy=ring[:, :2],
                              z=float(np.median(ring[:, 2])),
                              area_m2=abs(_shoelace(ring[:, :2]))))
    return out


def doors(scene: str) -> list[Door]:
    raw = json.loads((DATA / "doors" / f"{scene}.json").read_text())["doors"]
    out = []
    for d in raw:
        v = np.asarray(d["vertices"], dtype=np.float64)
        n = np.asarray(d["normal"], dtype=np.float64)
        n_xy = n[:2]
        if np.linalg.norm(n_xy) < 0.5:    # a horizontal "door" is a hatch, not a doorway
            continue
        n_xy = n_xy / np.linalg.norm(n_xy)
        along = np.array([-n_xy[1], n_xy[0]])
        proj = v[:, :2] @ along
        out.append(Door(centre_xy=v[:, :2].mean(axis=0), normal_xy=n_xy,
                        width_m=float(proj.max() - proj.min()), bottom_z=float(v[:, 2].min())))
    return out


def _probe(patches: list[FloorPatch], start: np.ndarray, direction: np.ndarray) -> int | None:
    """Index of the first patch hit stepping from `start` along `direction`."""
    steps = np.arange(PROBE_STEP_M, PROBE_MAX_M + 1e-9, PROBE_STEP_M)
    pts = start[None, :] + steps[:, None] * direction[None, :]
    hits = np.stack([p.contains(pts) for p in patches])      # (patches, steps)
    for s in range(len(steps)):
        idx = np.nonzero(hits[:, s])[0]
        if len(idx):
            return int(idx[0])
    return None


def storeys(scene: str, *, room_min_area_m2: float) -> list[Storey]:
    """Group the building's floor patches into levels and attach the doors on each."""
    patches = floor_patches(scene)
    if not patches:
        return []
    # Storeys are defined by the room-sized patches. Clustering on every patch instead chains
    # whole buildings together through window sills and stair treads, which sit at heights
    # between two floors: 5LpN3gDmAk7 came back as one 20-room "storey" spanning -1.3 to 3.2 m.
    big = sorted([p for p in patches if p.area_m2 >= room_min_area_m2], key=lambda p: p.z)
    if not big:
        return []
    levels: list[list[FloorPatch]] = [[big[0]]]
    for p in big[1:]:
        if p.z - levels[-1][-1].z > STOREY_GAP_M:
            levels.append([])
        levels[-1].append(p)
    centres = [float(np.median([p.z for p in lv])) for lv in levels]

    small = [p for p in patches if p.area_m2 < room_min_area_m2]
    extra: list[list[FloorPatch]] = [[] for _ in levels]
    for p in small:
        i = int(np.argmin([abs(p.z - c) for c in centres]))
        if abs(p.z - centres[i]) <= STOREY_GAP_M:
            extra[i].append(p)

    all_doors = doors(scene)
    out = []
    for i, level in enumerate(levels):
        rooms = sorted(level, key=lambda p: p.entity)
        connectors = sorted(extra[i], key=lambda p: p.entity)
        if len(rooms) < 2:
            continue
        z = centres[i]
        # A door belongs to the level its sill stands on.
        mine = [d for d in all_doors if abs(d.bottom_z - z) <= DOOR_SILL_TOL_M]
        edges, exterior, unplaced, same = set(), 0, 0, 0
        for d in mine:
            a = _probe(rooms, d.centre_xy, d.normal_xy)
            b = _probe(rooms, d.centre_xy, -d.normal_xy)
            if a is None and b is None:
                unplaced += 1
            elif a is None or b is None:
                exterior += 1
            elif a == b:
                same += 1
            else:
                edges.add((min(a, b), max(a, b)))
        out.append(Storey(scene=scene, index=i, z=z, rooms=rooms, connectors=connectors,
                          doors=mine, edges=edges, exterior_doors=exterior,
                          unplaced_doors=unplaced, same_room_doors=same))
    return out
