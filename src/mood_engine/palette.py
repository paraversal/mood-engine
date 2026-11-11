"""Area-weighted palette extraction: k-means in OKLab on a downsampled image."""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image

from .color import oklab_to_hex, srgb_to_oklab


@dataclass
class Cluster:
    lab: np.ndarray   # OKLab centre
    weight: float     # fraction of image area (sums to 1 over the palette)

    @property
    def hex(self) -> str:
        return oklab_to_hex(self.lab)


def image_to_lab(img: Image.Image, max_side: int = 96) -> np.ndarray:
    """Downsample (keeping aspect) and return (N, 3) OKLab pixels."""
    img = img.convert("RGB")
    img.thumbnail((max_side, max_side), Image.Resampling.BOX)
    rgb = np.asarray(img, dtype=float).reshape(-1, 3) / 255.0
    return srgb_to_oklab(rgb)


def image_signature(img: Image.Image, size: tuple[int, int] = (16, 9)) -> np.ndarray:
    """A tiny OKLab grid of the image (aspect ignored) for spotting re-uploads."""
    small = img.convert("RGB").resize(size, Image.Resampling.BOX)
    return srgb_to_oklab(np.asarray(small, dtype=float) / 255.0)


def load_image(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def kmeans(x: np.ndarray, k: int = 8, iters: int = 20, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Plain k-means with k-means++ init. Returns (centres, weights) with empty
    clusters dropped; deterministic for a given seed."""
    rng = np.random.default_rng(seed)
    n = len(x)
    centres = [x[rng.integers(n)]]
    d2 = ((x - centres[0]) ** 2).sum(axis=1)
    for _ in range(1, k):
        total = d2.sum()
        if total <= 1e-12:  # fewer distinct colours than k
            break
        centres.append(x[rng.choice(n, p=d2 / total)])
        d2 = np.minimum(d2, ((x - centres[-1]) ** 2).sum(axis=1))
    c = np.array(centres)
    labels = np.zeros(n, dtype=int)
    for _ in range(iters):
        dist = ((x[:, None, :] - c[None, :, :]) ** 2).sum(axis=2)
        new = dist.argmin(axis=1)
        for j in range(len(c)):
            m = new == j
            if m.any():
                c[j] = x[m].mean(axis=0)
        if np.array_equal(new, labels):
            break
        labels = new
    dist = ((x[:, None, :] - c[None, :, :]) ** 2).sum(axis=2)
    labels = dist.argmin(axis=1)
    counts = np.bincount(labels, minlength=len(c)).astype(float)
    keep = counts > 0
    return c[keep], counts[keep] / n


def extract_palette(img: Image.Image, k: int = 8, max_side: int = 96) -> list[Cluster]:
    lab = image_to_lab(img, max_side)
    centres, weights = kmeans(lab, k=k)
    order = np.argsort(-weights)
    return [Cluster(centres[i], float(weights[i])) for i in order]
