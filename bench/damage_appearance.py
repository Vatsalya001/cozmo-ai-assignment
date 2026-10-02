"""Can a defect class be NAMED from appearance alone? Measured on BD3, trained at run time.

    python bench/damage_appearance.py                  # full run, writes results/damage_appearance.json
    python bench/damage_appearance.py --max-train 800   # subsample the training set
    python bench/damage_appearance.py --no-cache        # ignore the feature cache

## What this is, and the gate it does NOT satisfy

`A-DMG-DETECT` asks for "staged damage found with the right class". There is no staged room in
this submission, so **this benchmark does not satisfy A-DMG-DETECT and must not be read as
doing so.** Nor does it validate `scanplan`'s own damage detector, which is geometric -- it
finds departures from a fitted wall plane and has no opinion about colour or texture. A bulge
and a mould patch are the same thing to it, and a photograph of mould on a flat wall is nothing
to it at all.

What is measured here is the *other half* of the problem, the half the geometric detector
cannot do: given a cropped photograph of a defect, **can its class be named?** That is a real
capability question with a real answer, and the answer is a number rather than an opinion.

## Why the features are deliberately primitive

Colour statistics, Canny edge density, gradient-magnitude and structure-tensor statistics, and
a hand-rolled uniform-LBP texture histogram. OpenCV and NumPy only -- no torch, no pretrained
backbone, no deep features. Two reasons, one principled and one practical:

- The LiDAR tier is specified to run lean and offline. A pretrained backbone would add a
  weights download and a ~2 GB dependency to a pipeline whose whole claim is that it does not
  need one. `scikit-learn` is therefore added under a NEW optional extra, `damage`, and not to
  the default dependencies.
- A primitive feature set gives a FLOOR, not a ceiling. If colour and texture statistics
  already separate these classes well above chance, that is evidence the classes are
  appearance-separable at all; it says nothing about how much better a ResNet would be. Read
  the number as "at least this much", never as "this is the limit".

## The split, and the leakage that cannot be ruled out

BD3's own publisher train/test parquet split is used verbatim -- no re-splitting, no shuffling
across the boundary. That is the best available split and it is **not a clean one**:

> The BD3 images are drawn from 50+ buildings, but the published parquet carries only
> `image`, `question` and `answer`. There is **no building id, no defect id, no filename, no
> capture timestamp**. So the split CANNOT be grouped by building or by physical defect, and
> two photographs of the *same crack on the same wall* may sit on opposite sides of it. This
> cannot be ruled out from the data available, and it would inflate the accuracy reported
> below by an unknown amount.

An exact-duplicate check (MD5 over the stored JPEG bytes) is run across the boundary, because
that much IS checkable. **It finds duplicates:** 20 of the 793 test rows are byte-for-byte
present in train. The accuracy is therefore also reported with those rows dropped -- the figure
is `split.exact_duplicate_check.accuracy_excluding_duplicate_test_rows` in the result file, and
no accuracy literal is repeated in this docstring, because the one that used to sit here drifted
to a value the test split cannot even produce. The correction is small; the useful part is not
its size, it is
what the duplicates prove -- the publisher's split was never deduplicated, which makes the
*undetectable* same-defect and same-building overlap more likely rather than less. MD5 is a weak
check and is labelled as one: re-encoding, cropping or a second exposure of one defect all
defeat it, so 20 is a lower bound on the overlap.

## Licence position -- why no weight file is committed

The HuggingFace re-release carries a `license: cc-by-4.0` tag. The tag does not hold, and the
chain behind it was checked rather than assumed: the card's own prose defers upstream ("follows
the same license as the original BD3 dataset", "all image rights and original credit belong to
the original authors"), and upstream `github.com/Praveenkottari/BD3-Dataset` has **no licence
file** -- the GitHub API reports `license: null` and its `/license` endpoint 404s. The deferral
terminates nowhere, so the images are treated as **licence-unknown**. Consequences, applied
rather than noted:

- the images are not redistributed -- `data/external/` is gitignored
- **no trained weight file is committed.** Model weights fitted on these images are arguably a
  derivative work of images whose licence is unknown, so they are not shipped. `--save-model`
  does not exist.
- the benchmark therefore TRAINS AT RUN TIME from the locally fetched dataset and publishes
  only the measured numbers, which are facts about the data and not copies of it.

So the shipped pipeline gains **no runtime appearance classifier**. What ships is a measured
benchmark of the capability, plus the honest statement that it is not wired in. Pretending
otherwise would be the easy version of this file.
"""
from __future__ import annotations

# Set before sklearn/OpenMP initialise: single-threaded fitting is what makes the reported
# numbers byte-reproducible rather than merely close.
import os

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import argparse
import hashlib
import json
import random
import time
from pathlib import Path

import cv2
import numpy as np

cv2.setNumThreads(1)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "external" / "bd3" / "data"
OUT = ROOT / "bench" / "results" / "damage_appearance.json"
CACHE = ROOT / "data" / "external" / "bd3" / "appearance_features.npz"

SEED = 0
WORK = 256          # features are computed at 256x256; the stored JPEGs are 512x512
FEATURE_VERSION = 2

# An ESTIMATE, and labelled as one everywhere it is published: 3,965 images at ~20 ms each,
# single-threaded. The run that writes the result file normally hits the feature cache, so it
# cannot measure this -- run with --no-cache and `timing.feature_extraction_s` is the real
# measured cold figure instead.
FEATURE_COLD_ESTIMATE_S = 80.0

# BD3 answer -> schema/output.schema.json damage class enum. "plain" is NOT a damage class: it
# is the negative / reject class, and keeping it in the problem is the point -- a classifier
# that cannot say "nothing here" would report damage on every clean wall it is shown.
LABEL_MAP = {
    "major_crack": "crack",
    "minor_crack": "crack",
    "stain": "water_stain",
    "algae": "mould",
    "peeling": "peeling_paint",
    "spalling": "hole",
    "plain": "plain",
}
NEGATIVE_CLASS = "plain"


# ----------------------------------------------------------------------------- texture

def _uniform_lbp_table() -> np.ndarray:
    """Rotation-invariant uniform LBP code table, written out rather than imported.

    A circular 8-bit pattern is *uniform* when it has at most two 0->1/1->0 transitions. Those
    patterns are the ones that correspond to recognisable local structure -- flat, edge, corner,
    line end -- and there are 58 of them, which collapse under rotation to the 9 bins "number of
    set bits". Everything else is noise-like and goes in one 10th bin. Ten bins over 65k pixels
    is a stable histogram; 256 raw codes over the same pixels is mostly sampling noise.
    """
    table = np.full(256, 9, dtype=np.uint8)
    for code in range(256):
        bits = [(code >> k) & 1 for k in range(8)]
        transitions = sum(bits[k] != bits[(k + 1) % 8] for k in range(8))
        if transitions <= 2:
            table[code] = sum(bits)
    return table


LBP_TABLE = _uniform_lbp_table()


def lbp_hist(gray: np.ndarray, radius: int) -> np.ndarray:
    """10-bin rotation-invariant uniform LBP histogram at one scale. NumPy shifts only."""
    r = radius
    g = gray.astype(np.int16)
    h, w = g.shape
    centre = g[r:h - r, r:w - r]
    code = np.zeros(centre.shape, dtype=np.uint8)
    offsets = [(-r, -r), (-r, 0), (-r, r), (0, r), (r, r), (r, 0), (r, -r), (0, -r)]
    for k, (dy, dx) in enumerate(offsets):
        nb = g[r + dy:h - r + dy, r + dx:w - r + dx]
        code |= ((nb >= centre).astype(np.uint8) << k)
    hist = np.bincount(LBP_TABLE[code].ravel(), minlength=10).astype(np.float64)
    return hist / max(code.size, 1)


# ----------------------------------------------------------------------------- features

_PCTS = (5, 25, 50, 75, 95)
_CHANNELS = ("B", "G", "R", "H", "S", "V", "L", "a", "b")
_LINE_KERNELS = [
    np.ones((1, 9), np.uint8),
    np.ones((9, 1), np.uint8),
    np.eye(9, dtype=np.uint8),
    np.fliplr(np.eye(9, dtype=np.uint8)).copy(),
]


def _chan_stats(x: np.ndarray) -> list[float]:
    f = x.astype(np.float32).ravel()
    return [float(f.mean()), float(f.std())] + [float(v) for v in np.percentile(f, _PCTS)]


def _grid_means(x: np.ndarray, n: int = 3) -> list[float]:
    s = x.shape[0] // n
    return [float(x[i * s:(i + 1) * s, j * s:(j + 1) * s].mean())
            for i in range(n) for j in range(n)]


def _block_stats(x: np.ndarray, n: int = 4) -> list[float]:
    s = x.shape[0] // n
    blocks = np.array([x[i * s:(i + 1) * s, j * s:(j + 1) * s].mean()
                       for i in range(n) for j in range(n)], dtype=np.float64)
    return [float(blocks.mean()), float(blocks.std()), float(blocks.max()), float(blocks.min())]


def extract(bgr: np.ndarray) -> np.ndarray:
    """One feature vector from one BGR image. Deterministic, no randomness, ~190 floats."""
    small = cv2.resize(bgr, (WORK, WORK), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB)
    f: list[float] = []

    # -- colour: per-channel distribution in three spaces. BGR for raw tone, HSV because
    #    algae/mould is a hue story, Lab because a/b separate stain brown from clean grey
    #    without dragging brightness in with them.
    for ch in (small[:, :, 0], small[:, :, 1], small[:, :, 2],
               hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2],
               lab[:, :, 0], lab[:, :, 1], lab[:, :, 2]):
        f += _chan_stats(ch)

    # -- colour layout: a 3x3 grid on L, a, b. Patchy discoloration and uniform discoloration
    #    have the same global mean and different grids.
    for ch in (lab[:, :, 0], lab[:, :, 1], lab[:, :, 2]):
        f += _grid_means(ch, 3)

    # -- coarse 2D hue x saturation histogram, 8 x 4 bins.
    hs = cv2.calcHist([hsv], [0, 1], None, [8, 4], [0, 180, 0, 256])
    f += (hs.ravel() / max(float(hs.sum()), 1.0)).astype(np.float64).tolist()

    # -- tone extremes: spalling exposes dark voids, peeling exposes bright substrate.
    v = hsv[:, :, 2].astype(np.float32)
    f += [float((v < 40).mean()), float((v > 215).mean()),
          float((lab[:, :, 0] < 60).mean()), float((lab[:, :, 0] > 200).mean())]

    # -- edges. Canny at two operating points because one threshold cannot serve a hairline
    #    crack and a spalled edge at the same time.
    for lo, hi in ((50, 150), (100, 220)):
        e = cv2.Canny(gray, lo, hi)
        f.append(float(e.mean()) / 255.0)
        f += [d / 255.0 for d in _grid_means(e.astype(np.float32), 4)]

    # -- linearity: the fraction of edge pixels that survive a morphological opening with a
    #    9-px line in each of four directions. A crack is a line and survives one of them; a
    #    mould blotch's edge is not and survives none. This is the one cue that separates
    #    "elongated" from merely "high edge density".
    e = cv2.Canny(gray, 50, 150)
    total = max(float((e > 0).sum()), 1.0)
    lin = [float((cv2.morphologyEx(e, cv2.MORPH_OPEN, k) > 0).sum()) / total for k in _LINE_KERNELS]
    f += lin + [max(lin), float(np.mean(lin)), max(lin) - min(lin)]

    # -- gradient magnitude and orientation.
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    f += [float(mag.mean()), float(mag.std())] + \
         [float(x) for x in np.percentile(mag, (50, 90, 99))] + [float(mag.max())]
    ang = np.mod(np.arctan2(gy, gx), np.pi)
    oh = np.bincount((ang / np.pi * 12).astype(np.int32).clip(0, 11).ravel(),
                     weights=mag.ravel(), minlength=12).astype(np.float64)
    oh /= max(oh.sum(), 1e-9)
    f += oh.tolist()
    ohs = np.sort(oh)[::-1]
    f += [float(ohs[0]), float(ohs[:3].sum()),
          float(-(oh * np.log(oh + 1e-12)).sum()),        # orientation entropy
          float(ohs[0] / max(oh.mean(), 1e-12))]          # peakedness

    # -- structure-tensor coherence, global and per 4x4 block. High where gradients agree on a
    #    direction, which is the formal version of the linearity cue above.
    jxx, jyy, jxy = (gx * gx), (gy * gy), (gx * gy)
    num = np.sqrt((jxx.mean() - jyy.mean()) ** 2 + 4.0 * jxy.mean() ** 2)
    f.append(float(num / max(jxx.mean() + jyy.mean(), 1e-9)))
    bxx = cv2.boxFilter(jxx, -1, (15, 15))
    byy = cv2.boxFilter(jyy, -1, (15, 15))
    bxy = cv2.boxFilter(jxy, -1, (15, 15))
    coh = np.sqrt((bxx - byy) ** 2 + 4.0 * bxy ** 2) / np.maximum(bxx + byy, 1e-9)
    f += [float(coh.mean()), float(coh.std())] + [float(x) for x in np.percentile(coh, (50, 90, 99))]
    f += _block_stats(coh, 4)

    # -- focus / texture energy.
    lap = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
    f += [float(lap.var()), float(np.abs(lap).mean())]

    # -- hand-rolled texture descriptor, two scales on grey plus one on the a channel (colour
    #    texture: algae is textured AND green, stain is textured and not).
    f += lbp_hist(gray, 1).tolist()
    f += lbp_hist(gray, 3).tolist()
    f += lbp_hist(lab[:, :, 1], 1).tolist()

    return np.asarray(f, dtype=np.float64)


def _feature_names() -> list[str]:
    n: list[str] = []
    for c in _CHANNELS:
        n += [f"{c}_mean", f"{c}_std"] + [f"{c}_p{p}" for p in _PCTS]
    for c in ("L", "a", "b"):
        n += [f"{c}_grid{i}" for i in range(9)]
    n += [f"hs_hist{i}" for i in range(32)]
    n += ["frac_v_dark", "frac_v_bright", "frac_l_dark", "frac_l_bright"]
    for tag in ("canny50", "canny100"):
        n += [f"{tag}_density"] + [f"{tag}_grid{i}" for i in range(16)]
    n += ["lin_h", "lin_v", "lin_d1", "lin_d2", "lin_max", "lin_mean", "lin_range"]
    n += ["mag_mean", "mag_std", "mag_p50", "mag_p90", "mag_p99", "mag_max"]
    n += [f"orient{i}" for i in range(12)]
    n += ["orient_top1", "orient_top3", "orient_entropy", "orient_peak"]
    n += ["coh_global", "coh_mean", "coh_std", "coh_p50", "coh_p90", "coh_p99",
          "coh_blk_mean", "coh_blk_std", "coh_blk_max", "coh_blk_min"]
    n += ["lap_var", "lap_absmean"]
    for tag in ("lbp_g_r1", "lbp_g_r3", "lbp_a_r1"):
        n += [f"{tag}_{i}" for i in range(10)]
    return n


FEATURE_NAMES = _feature_names()


# ----------------------------------------------------------------------------- dataset

INSTALL_HINT = "pip install -e '.[damage]'"


def _require_extra() -> None:
    """Fail in one second, naming the install command, rather than mid-run with a bare
    ModuleNotFoundError.

    `scikit-learn` and `pyarrow` are both in the OPTIONAL `[damage]` extra -- deliberately,
    because the LiDAR tier must stay lean and offline. The cost of that choice is that the
    README's default `.[dev]` install reaches this file and dies. It used to die twice over and
    both times late: pandas raises a bare "Unable to find a usable engine" only when
    `read_parquet` is called, and the sklearn import sits after the ~80 s cold feature pass.
    """
    missing = []
    for mod, what in (("pandas", "pandas (reads BD3's parquet)"),
                      ("pyarrow", "pyarrow (pandas' parquet engine; nothing else pulls it in)"),
                      ("sklearn", "scikit-learn (fits the classifier)")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(what)
    if missing:
        raise SystemExit(
            "bench/damage_appearance.py needs the optional [damage] extra. Missing:\n"
            + "".join(f"    - {m}\n" for m in missing)
            + f"    install with:  {INSTALL_HINT}")


def _load_rows(use_cache: bool = True) -> tuple[dict[str, np.ndarray], bool]:
    """Features + labels + publisher split + a byte MD5 per image, cached to data/external/.

    Returns the arrays and whether this was a COLD pass (features recomputed from the JPEGs)
    or a warm one (read from the gitignored `.npz`). The caller publishes which it was, because
    a warm total and a cold total differ by about 80 s and reporting one as the other is how
    the timing block became self-contradictory.
    """
    if use_cache and CACHE.is_file():
        d = np.load(CACHE, allow_pickle=False)
        if int(d["version"][0]) == FEATURE_VERSION and d["X"].shape[1] == len(FEATURE_NAMES):
            return {k: d[k] for k in ("X", "y_raw", "split", "md5")}, False

    import pandas as pd

    files = sorted(DATA.glob("*.parquet"))
    if not files:
        raise SystemExit(f"no parquet in {DATA} -- run scripts/fetch_bd3.py first")
    X, y_raw, split, md5 = [], [], [], []
    for path in files:
        fold = "test" if path.name.startswith("test") else "train"
        df = pd.read_parquet(path)
        print(f"  {path.name}: {len(df)} rows ({fold})", flush=True)
        for rec, answer in zip(df["image"].to_numpy(), df["answer"].to_numpy()):
            raw = rec["bytes"]
            img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue
            X.append(extract(img))
            y_raw.append(str(answer))
            split.append(fold)
            md5.append(hashlib.md5(raw).hexdigest())
    out = {"X": np.asarray(X, dtype=np.float64), "y_raw": np.asarray(y_raw),
           "split": np.asarray(split), "md5": np.asarray(md5)}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(CACHE, version=np.array([FEATURE_VERSION]), **out)
    return out, True


def _counts(labels: np.ndarray) -> dict[str, int]:
    vals, cnt = np.unique(labels, return_counts=True)
    return {str(v): int(c) for v, c in zip(vals, cnt)}


# ----------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--max-train", type=int, default=0,
                    help="subsample the training set to N images (0 = use all)")
    ap.add_argument("--no-cache", action="store_true", help="recompute features")
    args = ap.parse_args()

    random.seed(SEED)
    np.random.seed(SEED)

    # Preflight, before a single image is decoded. Both of these live in the OPTIONAL [damage]
    # extra, and both were previously discovered LATE -- pyarrow only when pandas reached
    # read_parquet, sklearn only after the ~80 s cold feature pass. Charging a reviewer that
    # much to learn an install command is the defect, not the missing package.
    _require_extra()

    t0 = time.time()
    print("extracting appearance features (OpenCV + NumPy only)")
    data, cold = _load_rows(use_cache=not args.no_cache)
    t_feat = time.time() - t0

    X, y_raw, split, md5 = data["X"], data["y_raw"], data["split"], data["md5"]
    y = np.asarray([LABEL_MAP[v] for v in y_raw])
    is_test = split == "test"
    tr_idx = np.flatnonzero(~is_test)
    te_idx = np.flatnonzero(is_test)

    subsampled = False
    n_train_available = int(tr_idx.size)
    if args.max_train and args.max_train < tr_idx.size:
        rng = np.random.default_rng(SEED)
        tr_idx = np.sort(rng.choice(tr_idx, size=args.max_train, replace=False))
        subsampled = True

    Xtr, ytr = X[tr_idx], y[tr_idx]
    Xte, yte = X[te_idx], y[te_idx]
    classes = sorted(set(y))

    # -- the one duplicate check the data actually permits. It FINDS duplicates, so the
    #    accuracy is also recomputed with the affected test rows dropped; that difference is
    #    the only part of the leakage that can be measured rather than merely admitted.
    dup = sorted(set(md5[tr_idx]) & set(md5[te_idx]))
    dup_mask = np.isin(md5[te_idx], list(dup)) if dup else np.zeros(te_idx.size, bool)
    dup_rows = int(dup_mask.sum())

    # -- model selection on a held-out slice of TRAIN only. Choosing on the test set would be
    #    the oldest way to inflate a reported accuracy, so the choice is made before test is
    #    touched and both candidates' validation scores are published.
    #    sklearn is in the OPTIONAL [damage] extra, so the README's default `.[dev]` install
    #    reaches this line and would raise a bare ModuleNotFoundError ~80 s in. `_require_extra`
    #    at the top of main() has already caught that and named the install command; the
    #    try/except here is the second line of defence for a half-installed environment.
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import accuracy_score, confusion_matrix
        from sklearn.model_selection import train_test_split
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        raise SystemExit(
            f"scikit-learn is missing or broken ({exc}). It is an OPTIONAL dependency on "
            f"purpose -- the LiDAR tier stays lean and offline, so it is not in the default "
            f"install.\n    install it with:  {INSTALL_HINT}") from None

    def candidates():
        return {
            "HistGradientBoostingClassifier": HistGradientBoostingClassifier(
                random_state=SEED, max_iter=300, learning_rate=0.1,
                early_stopping=False, l2_regularization=1.0),
            "LogisticRegression": make_pipeline(
                StandardScaler(),
                LogisticRegression(max_iter=3000, C=1.0, random_state=SEED)),
        }

    Xa, Xb, ya, yb = train_test_split(Xtr, ytr, test_size=0.25, random_state=SEED, stratify=ytr)
    val = {}
    for name, model in candidates().items():
        model.fit(Xa, ya)
        val[name] = round(float(accuracy_score(yb, model.predict(Xb))), 4)
        print(f"  inner-validation {name}: {val[name]:.4f}", flush=True)
    chosen = max(val, key=lambda k: (val[k], k))

    model = candidates()[chosen]
    t1 = time.time()
    model.fit(Xtr, ytr)
    t_fit = time.time() - t1
    pred = model.predict(Xte)

    overall = float(accuracy_score(yte, pred))
    cm = confusion_matrix(yte, pred, labels=classes)

    keep = ~dup_mask
    overall_dedup = float(accuracy_score(yte[keep], pred[keep])) if keep.any() else 0.0
    acc_on_dups = float(accuracy_score(yte[dup_mask], pred[dup_mask])) if dup_rows else None

    per_class = {}
    for i, c in enumerate(classes):
        tp = int(cm[i, i])
        support = int(cm[i].sum())
        predicted = int(cm[:, i].sum())
        per_class[c] = {
            "precision": round(tp / predicted, 4) if predicted else 0.0,
            "recall": round(tp / support, 4) if support else 0.0,
            "f1": round(2 * tp / (predicted + support), 4) if (predicted + support) else 0.0,
            "support": support,
            "predicted": predicted,
        }

    # -- baselines. Two, because the mapping merges two crack grades into one class and so
    #    changes what "always guess the biggest class" is worth. The MAPPED one is the binding
    #    comparison: it is the problem the model is actually solving, and it is the harder bar.
    raw_counts_te = _counts(y_raw[te_idx])
    mapped_counts_te = _counts(yte)
    raw_major = max(raw_counts_te.items(), key=lambda kv: (kv[1], kv[0]))
    mapped_major = max(mapped_counts_te.items(), key=lambda kv: (kv[1], kv[0]))
    base_raw = raw_major[1] / len(te_idx)
    base_mapped = mapped_major[1] / len(te_idx)

    # -- the negative class, scored on its own terms: "did it ever claim damage on a clean
    #    wall". A detector that cannot decline is worse than useless on a survey round.
    neg = per_class.get(NEGATIVE_CLASS, {})
    plain_rows = np.flatnonzero(yte == NEGATIVE_CLASS)
    damage_rows = np.flatnonzero(yte != NEGATIVE_CLASS)
    false_alarm = float((pred[plain_rows] != NEGATIVE_CLASS).mean()) if plain_rows.size else 0.0
    missed = float((pred[damage_rows] == NEGATIVE_CLASS).mean()) if damage_rows.size else 0.0
    damage_only = float((pred[damage_rows] == yte[damage_rows]).mean()) if damage_rows.size else 0.0
    # The three outcomes a damage row can have PARTITION it: right class, called clean, or
    # given the wrong damage class. The wrong-class share is the residual of the other two --
    # NOT 1 - damage_only, which was the published figure and double-counted the called-clean
    # rows the same sentence itemises separately (15.5% where the truth is 15.2%).
    wrong_class = max(0.0, 1.0 - damage_only - missed)

    # One number, one characterisation. "trained in seconds" used to sit in what_this_closes
    # next to a 35 s fit and a ~2.5 min cold total -- three readings of one run in one file.
    # Both figures below are now formatted from the measured/estimated values themselves.
    elapsed = time.time() - t0
    cold_total = elapsed + (0.0 if cold else FEATURE_COLD_ESTIMATE_S - t_feat)

    result = {
        "question": "can a building-defect class be NAMED from appearance alone, with "
                    "OpenCV/NumPy features and a scikit-learn classifier trained at run time?",
        # The narrowing travels WITH the number, in the one field a skim-reader reads. The
        # gate caveat used to be carried here and the leakage caveat did not, which made the
        # omission selective rather than an oversight. Every figure is formatted from a
        # computed value so it cannot drift from the matrix the way a literal did.
        "answer": (f"yes, {overall:.1%} over 6 classes on the publisher's held-out test split, "
                   f"against a {base_mapped:.1%} majority-class baseline on the same split. "
                   f"Read it as an UPPER BOUND, not a cross-building estimate: the split "
                   f"carries no building id so it CANNOT be grouped by building, and "
                   f"{dup_rows} of {int(te_idx.size)} test rows are byte-identical to train "
                   f"({overall_dedup:.1%} with those dropped)"),
        "gate_status": "NOT a gate result. A-DMG-DETECT is NOT satisfied by this file -- see "
                       "what_this_does_not_close",
        "dataset": {
            "name": "BD3 (Building Defect Detection Dataset), HuggingFace parquet re-release",
            "local_path": "data/external/bd3/data (gitignored, fetched by scripts/fetch_bd3.py)",
            "images": int(X.shape[0]),
            "image_size": "512x512 JPEG, features computed at 256x256",
            "question_column": "constant across all rows; carries no information and is unused",
            "raw_labels": _counts(y_raw),
            "label_map_to_schema_enum": LABEL_MAP,
            "negative_class": f"'{NEGATIVE_CLASS}' is not a damage class -- it is the reject "
                              "class, kept in the problem because a classifier that cannot say "
                              "'nothing here' would report damage on every clean wall",
        },
        "split": {
            "kind": "the publisher's own train/test parquet split, used verbatim",
            "train_images": int(tr_idx.size),
            "train_images_available": n_train_available,
            "test_images": int(te_idx.size),
            "subsampled": subsampled,
            "held_out": "the 793 rows of test-00000-of-00001.parquet. The model never sees them "
                        "during feature selection, model selection or fitting; model choice was "
                        "made on a 25% slice of TRAIN only.",
            "leakage_cannot_be_ruled_out": (
                "BD3's images come from 50+ buildings, but the published parquet carries only "
                "image/question/answer -- NO building id, NO defect id, NO filename, NO "
                "timestamp. The split therefore CANNOT be grouped by building or by physical "
                "defect, and two photographs of the SAME crack on the SAME wall may sit on "
                "opposite sides of it. This cannot be ruled out from the data available and it "
                "would inflate the accuracy below by an unknown amount. The honest reading is "
                "'at most this good on unseen buildings', not 'this good'."),
            "exact_duplicate_check": {
                "method": "MD5 over the stored JPEG bytes, train vs test",
                "duplicate_digests": len(dup),
                "test_rows_affected": dup_rows,
                "found": bool(dup_rows),
                "accuracy_excluding_duplicate_test_rows": round(overall_dedup, 4),
                "accuracy_on_the_duplicate_rows_alone": (
                    round(acc_on_dups, 4) if acc_on_dups is not None else None),
                "reading": (
                    f"byte-identical images DO cross the publisher's split: {dup_rows} of "
                    f"{int(te_idx.size)} test rows ({dup_rows / max(int(te_idx.size), 1):.1%}) "
                    "are byte-for-byte present in train. Dropping them moves overall accuracy "
                    f"from {overall:.4f} to {overall_dedup:.4f}, so this detectable slice of the "
                    "leakage is small. Two things make it worth reporting anyway. The model "
                    f"scores {acc_on_dups:.0%} on exactly those rows versus {overall_dedup:.1%} "
                    "elsewhere, which is what memorisation looks like and confirms the "
                    "mechanism is real rather than theoretical. And it is proof the publisher's "
                    "split was never deduplicated, which makes the UNDETECTABLE "
                    "same-defect/same-building overlap more likely, not less -- there is no "
                    "evidence anyone tried to prevent it."
                    if dup_rows else "no byte-identical images cross the split."),
                "why_this_is_weak": "byte identity catches only re-uploads of the same file. "
                                    "Re-encoding, cropping, or a second exposure of one defect "
                                    "all defeat it, so this count is a lower bound on overlap "
                                    "and a clean result here would NOT have been evidence of a "
                                    "clean split.",
            },
        },
        "features": {
            "libraries": ["opencv-python", "numpy"],
            "no_deep_features": "no torch, no pretrained backbone, no learned embedding",
            "dimension": int(X.shape[1]),
            "groups": [
                "per-channel distribution stats (mean/std/p5/p25/p50/p75/p95) in BGR, HSV, Lab",
                "3x3 grid means on L/a/b (patchy vs uniform discoloration)",
                "coarse 8x4 hue-saturation 2D histogram",
                "dark/bright area fractions on V and L",
                "Canny edge density at two thresholds, global and on a 4x4 grid",
                "morphological line-opening survival in 4 directions (elongation, for cracks)",
                "Sobel gradient-magnitude stats and a 12-bin orientation histogram "
                "(+entropy, peakedness)",
                "structure-tensor coherence, global and per 4x4 block",
                "Laplacian variance and mean absolute response",
                "hand-rolled rotation-invariant uniform LBP, 10 bins, at radius 1 and 3 on grey "
                "and radius 1 on the Lab a channel",
            ],
            "why_primitive": "these features give a FLOOR, not a ceiling. They show the classes "
                             "are appearance-separable; they say nothing about how much better a "
                             "pretrained backbone would be.",
        },
        "model": {
            "chosen": chosen,
            "library": "scikit-learn",
            "dependency_position": "scikit-learn is in a NEW optional extra [damage] in "
                                   "pyproject.toml, NOT in the default dependencies, because the "
                                   "LiDAR tier must stay lean and offline",
            "selection": "chosen by accuracy on a 25% stratified slice of TRAIN, before the test "
                         "split was touched",
            "inner_validation_accuracy": val,
            "seed": SEED,
            "determinism": "SEED=0 on numpy, the stratified inner split and the estimator; "
                           "OMP/BLAS/OpenCV pinned to one thread; features involve no "
                           "randomness. Verified by re-running: every measured field in this "
                           "file is identical across runs. The `timing` block is the sole "
                           "exception -- it is wall clock, and it is not a measurement of the "
                           "model.",
        },
        "accuracy_overall": round(overall, 4),
        "baseline_majority_class": {
            "binding": {
                "accuracy": round(base_mapped, 4),
                "class": mapped_major[0],
                "count": mapped_major[1],
                "of": int(te_idx.size),
                "note": "majority class AFTER mapping to the schema enum -- the problem the "
                        "model actually solves, and the harder bar because major_crack and "
                        "minor_crack merge into one class",
            },
            "raw_labels": {
                "accuracy": round(base_raw, 4),
                "class": raw_major[0],
                "count": raw_major[1],
                "of": int(te_idx.size),
                "note": "majority class over BD3's 7 raw labels, reported for comparability with "
                        "the dataset's own literature",
            },
        },
        "beats_baseline": bool(overall > base_mapped),
        "margin_over_binding_baseline": round(overall - base_mapped, 4),
        "per_class": per_class,
        "confusion_matrix": {
            "labels": classes,
            "rows_are_true_cols_are_predicted": [[int(v) for v in row] for row in cm],
        },
        "biggest_confusions": [
            {"true": classes[i], "predicted": classes[j], "n": int(cm[i, j]),
             "share_of_true_class": round(float(cm[i, j]) / max(int(cm[i].sum()), 1), 4)}
            for i, j in sorted(
                ((i, j) for i in range(len(classes)) for j in range(len(classes)) if i != j),
                key=lambda ij: -cm[ij[0], ij[1]])[:5]
        ],
        "where_it_fails": (
            "the errors are concentrated, not spread: water_stain and peeling_paint are the two "
            "weak classes and they bleed into each other and into crack. That is the expected "
            "failure for this feature set -- a stain and a peeled patch are both irregular "
            "discoloured regions, and the colour/texture statistics that separate green algae "
            "from grey concrete have much less to work with between two shades of brown. "
            "Meanwhile 'plain' is the strongest class, which matters more than it looks: the "
            "easiest thing to get right is 'nothing is wrong here'."),
        "reject_class_behaviour": {
            "plain_precision": neg.get("precision"),
            "plain_recall": neg.get("recall"),
            "false_alarm_rate_on_plain": round(false_alarm, 4),
            "missed_damage_rate": round(missed, 4),
            "accuracy_on_damage_rows_only": round(damage_only, 4),
            "wrong_damage_class_rate": round(wrong_class, 4),
            "the_three_rates_partition_damage_rows": (
                "accuracy_on_damage_rows_only + missed_damage_rate + wrong_damage_class_rate "
                "= 1 over the damage rows, by construction. wrong_damage_class_rate is the "
                "RESIDUAL, not 1 - accuracy_on_damage_rows_only: that subtraction is total "
                "damage-row error and double-counts the called-clean rows."),
            "reading": (
                "false_alarm_rate_on_plain is the share of clean walls called damaged "
                f"({false_alarm:.1%}); missed_damage_rate is the share of real defects called "
                f"clean ({missed:.1%}). On a survey round the second costs more -- a missed "
                "defect leaves the report -- and it is the "
                f"{'LARGER' if missed > false_alarm else 'SMALLER'} of the two here. What is "
                f"left is {wrong_class:.1%} of damage rows given the WRONG damage class, "
                "which is a scoping error rather than a missed defect: the wall gets surveyed, "
                "the line item is mislabelled."),
        },
        "licence_position": {
            "verdict": "licence-unknown",
            "source": "BD3 (Kottari & Arjunan, 2024), re-released as the HuggingFace VQA "
                      "dataset chandrabhuma/building_defect_vqa, revision "
                      "520fef082f3b2bf42d5301f885079f74bac839de",
            "huggingface_tag": "tagged license: cc-by-4.0 in the card's YAML",
            "why_the_tag_does_not_hold": [
                "the card's own prose contradicts its tag: under 'License' it says the dataset "
                "'follows the same license as the original BD3 dataset' and that 'all image "
                "rights and original credit belong to the original authors' -- that is a "
                "deferral upstream, not a CC-BY grant",
                "upstream github.com/Praveenkottari/BD3-Dataset has NO licence: the GitHub API "
                "reports license: null and the /license endpoint returns 404 (checked, not "
                "assumed)",
                "so the deferral terminates nowhere, and a permissive tag applied downstream "
                "cannot create rights the upstream never granted",
            ],
            "consequences_applied": [
                "the images are NOT redistributed -- data/external/ is gitignored",
                "NO trained weight file is committed: weights fitted on these images are "
                "arguably a derivative work of images whose licence is unknown",
                "the benchmark TRAINS AT RUN TIME from the locally fetched dataset and "
                "publishes only measured numbers, which are facts about the data, not copies "
                "of it",
            ],
            "weights_shipped": False,
        },
        "what_this_closes": (
            "it puts a measured number on one capability the submission previously only asserted: "
            f"a defect class can be named from appearance alone at {overall:.1%} over 6 classes "
            f"({base_mapped:.1%} baseline) using nothing but OpenCV colour/edge/gradient/texture "
            "statistics and a scikit-learn classifier -- no deep model, no weights download, "
            f"~{t_fit:.0f} s to fit and ~{cold_total / 60:.1f} min end to end cold (see the "
            "timing block, which says which of its figures are measured and which estimated). "
            "It also quantifies which classes are confusable, and shows the "
            "reject class is learnable, so 'clean wall' is a prediction the approach can make "
            "rather than a case it ignores."),
        "what_this_does_not_close": [
            "A-DMG-DETECT ('staged damage found with the right class') is NOT satisfied. There "
            "is no staged room in this submission, so there is nothing to find; this file "
            "classifies cropped photographs that are handed to it already centred on a defect.",
            "it does not validate scanplan's own damage detector, which is GEOMETRIC -- it finds "
            "departures from a fitted wall plane. That is a different thing entirely: a bulge and "
            "a mould patch are identical to it, and mould on a flat wall is invisible to it. "
            "Nothing here transfers to that detector's accuracy.",
            "no detection and no localisation: no bounding box, no outline, no 'is there a defect "
            "in this wall image', only 'which of 6 classes is this crop'.",
            "no size, so nothing feeds width_m/height_m/area_m2 in the output schema, which is "
            "where the damage scope actually comes from.",
            "it does not ship. The pipeline gains NO runtime appearance classifier -- the licence "
            "position forbids committing weights and the extra is optional. What ships is this "
            "measurement.",
            "the split cannot be grouped by building, so the number is an upper bound on "
            "cross-building performance, not an estimate of it.",
        ],
        "timing": {
            "note": "wall clock, the only block in this file that is not reproducible run to "
                    "run. Every field says whether it is from a COLD run (features recomputed "
                    "from the 3,965 JPEGs) or a WARM one (features read from the gitignored "
                    "cache), because the two differ by ~80 s and the block previously printed "
                    "a warm total NEXT TO a larger cold figure, which cannot both be true.",
            "run_was_cold": bool(cold),
            "feature_extraction_s": round(t_feat, 1),
            "feature_extraction_cold_estimate_s": FEATURE_COLD_ESTIMATE_S,
            "feature_extraction_note": (
                "feature_extraction_s is measured by THIS run and run_was_cold says which kind "
                "of run it was. feature_extraction_cold_estimate_s is an ESTIMATE, not a "
                "measurement by the run that writes this file: 3,965 images at ~20 ms each, "
                "single-threaded. --no-cache forces a real cold pass, and then "
                "feature_extraction_s is the measured cold figure and run_was_cold is true. "
                "No subsampling was needed to stay inside budget."),
            "fit_s": round(t_fit, 2),
            "total_s": round(elapsed, 1),
            "total_s_kind": "cold" if cold else "warm",
            "cold_total_estimate_s": round(cold_total, 1),
            "not_in_the_pipeline": "this benchmark is not on the A-RUNTIME path; it runs "
                                   "offline and adds 0 s to the capture pipeline",
        },
        "reproduce": "python scripts/fetch_bd3.py && python bench/damage_appearance.py",
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, sort_keys=False) + "\n")

    print(f"\n{chosen}: overall {overall:.4f} vs baseline {base_mapped:.4f} "
          f"({mapped_major[0]} {mapped_major[1]}/{len(te_idx)})")
    for c in classes:
        p = per_class[c]
        print(f"  {c:<14} P {p['precision']:.3f}  R {p['recall']:.3f}  n {p['support']}")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
