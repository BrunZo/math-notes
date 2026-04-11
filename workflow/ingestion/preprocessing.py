"""Image preprocessing: deskew, denoise, contrast-normalize photos of handwritten notes.

Deterministic pipeline — no LLM calls. Designed for phone-camera photos of
whiteboard/paper notes (tested with Samsung Galaxy A15, 4080x3060 JPEGs).

Usage:
    preprocess(image_path) -> Path   # returns path to processed image (overwrites in-place)
    preprocess_all(paths)  -> None   # batch version
"""
import math
from pathlib import Path

import cv2
import numpy as np

from workflow.base import setup_logging

log = setup_logging("preprocessing")

# ── EXIF orientation ────────────────────────────────────────────────────────

_EXIF_ORIENTATION_TAG = 0x0112

_ORIENTATION_OPS: dict[int, list] = {
    # value -> list of (rotate_code | "flip") operations
    2: ["flip_h"],
    3: [cv2.ROTATE_180],
    4: ["flip_v"],
    5: ["flip_h", cv2.ROTATE_90_COUNTERCLOCKWISE],
    6: [cv2.ROTATE_90_CLOCKWISE],
    7: ["flip_h", cv2.ROTATE_90_CLOCKWISE],
    8: [cv2.ROTATE_90_COUNTERCLOCKWISE],
}


def _fix_orientation(img: np.ndarray, path: Path) -> np.ndarray:
    """Apply EXIF orientation to the image pixels, then return corrected image."""
    try:
        import struct

        data = path.read_bytes()
        if data[:2] != b"\xff\xd8":
            return img

        # Find EXIF APP1 marker
        pos = 2
        while pos < len(data) - 4:
            marker = struct.unpack(">H", data[pos : pos + 2])[0]
            if marker == 0xFFE1:  # APP1
                break
            length = struct.unpack(">H", data[pos + 2 : pos + 4])[0]
            pos += 2 + length
        else:
            return img

        exif_start = pos + 4  # skip marker + length
        if data[exif_start : exif_start + 4] != b"Exif":
            return img

        tiff_start = exif_start + 6
        byte_order = data[tiff_start : tiff_start + 2]
        if byte_order == b"II":
            endian = "<"
        elif byte_order == b"MM":
            endian = ">"
        else:
            return img

        ifd_offset = struct.unpack(endian + "I", data[tiff_start + 4 : tiff_start + 8])[0]
        ifd_pos = tiff_start + ifd_offset
        num_entries = struct.unpack(endian + "H", data[ifd_pos : ifd_pos + 2])[0]

        orientation = 1
        for i in range(num_entries):
            entry_pos = ifd_pos + 2 + i * 12
            tag = struct.unpack(endian + "H", data[entry_pos : entry_pos + 2])[0]
            if tag == _EXIF_ORIENTATION_TAG:
                orientation = struct.unpack(
                    endian + "H", data[entry_pos + 8 : entry_pos + 10]
                )[0]
                break

        ops = _ORIENTATION_OPS.get(orientation)
        if not ops:
            return img

        for op in ops:
            if op == "flip_h":
                img = cv2.flip(img, 1)
            elif op == "flip_v":
                img = cv2.flip(img, 0)
            else:
                img = cv2.rotate(img, op)

        log.debug("applied EXIF orientation %d to %s", orientation, path.name)
        return img

    except Exception:
        return img


# ── Deskew ──────────────────────────────────────────────────────────────────

_MAX_SKEW_DEG = 15.0  # ignore angles beyond this — likely a detection error


def _estimate_skew(gray: np.ndarray) -> float:
    """Estimate skew angle in degrees using Hough line detection on edges."""
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)

    # Dilate to connect broken text lines
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 1))
    edges = cv2.dilate(edges, kernel, iterations=1)

    lines = cv2.HoughLinesP(
        edges, rho=1, theta=np.pi / 180, threshold=100,
        minLineLength=gray.shape[1] // 6, maxLineGap=20,
    )
    if lines is None or len(lines) < 3:
        return 0.0

    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        dx, dy = x2 - x1, y2 - y1
        if abs(dx) < 5:
            continue
        angle = math.degrees(math.atan2(dy, dx))
        # Only consider near-horizontal lines (text lines)
        if abs(angle) < _MAX_SKEW_DEG:
            angles.append(angle)

    if not angles:
        return 0.0

    return float(np.median(angles))


def _deskew(img: np.ndarray, gray: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Rotate the image to correct skew. Returns (corrected_img, corrected_gray)."""
    angle = _estimate_skew(gray)
    if abs(angle) < 0.3:
        return img, gray

    h, w = img.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)

    # Use white border for color, white for gray
    img = cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_CONSTANT,
                         borderValue=(255, 255, 255))
    gray = cv2.warpAffine(gray, M, (w, h), borderMode=cv2.BORDER_CONSTANT,
                          borderValue=255)
    log.debug("deskewed by %.1f°", angle)
    return img, gray


# ── Denoise ─────────────────────────────────────────────────────────────────

def _denoise(gray: np.ndarray) -> np.ndarray:
    """Light denoising that preserves handwriting strokes."""
    return cv2.fastNlMeansDenoising(gray, h=8, templateWindowSize=7, searchWindowSize=21)


# ── Contrast normalization ──────────────────────────────────────────────────

def _normalize_contrast(gray: np.ndarray) -> np.ndarray:
    """Adaptive contrast normalization via CLAHE, then white-balance the background.

    This handles uneven lighting from phone cameras (shadows, desk lamp hotspots).
    """
    # CLAHE for local contrast
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    # Background estimation: heavy blur → treat as illumination field
    bg = cv2.GaussianBlur(enhanced, (0, 0), sigmaX=51)

    # Normalize: pixel / background * 255, clamped
    normalized = cv2.divide(enhanced, bg, scale=255)

    return normalized


# ── Sharpen ─────────────────────────────────────────────────────────────────

def _sharpen(gray: np.ndarray) -> np.ndarray:
    """Gentle unsharp mask to restore crispness after denoising."""
    blurred = cv2.GaussianBlur(gray, (0, 0), sigmaX=2)
    return cv2.addWeighted(gray, 1.3, blurred, -0.3, 0)


# ── Multi-page split ───────────────────────────────────────────────────────

_MIN_PAGE_HEIGHT_RATIO = 0.25  # a page must be at least 25% of total height


def _detect_pages(gray: np.ndarray) -> list[tuple[int, int]]:
    """Detect horizontal splits if the photo contains multiple pages side-by-side
    or stacked. Returns list of (y_start, y_end) for each detected page.

    For a single page, returns [(0, height)].
    """
    h, w = gray.shape

    # Project horizontally: sum pixel values per row (white = 255, dark = lower)
    # Invert so text rows have high values
    inv = 255 - gray
    row_sums = inv.sum(axis=1).astype(float)

    # Smooth the projection
    kernel_size = max(h // 50, 5)
    if kernel_size % 2 == 0:
        kernel_size += 1
    smoothed = cv2.GaussianBlur(row_sums.reshape(-1, 1), (1, kernel_size), 0).flatten()

    # Find valleys (low ink density) that could be page boundaries
    threshold = smoothed.max() * 0.05
    min_gap = h // 20  # minimum gap height

    in_gap = False
    gap_start = 0
    gaps: list[tuple[int, int]] = []

    for y in range(h):
        if smoothed[y] < threshold:
            if not in_gap:
                gap_start = y
                in_gap = True
        else:
            if in_gap:
                gap_len = y - gap_start
                if gap_len >= min_gap:
                    gaps.append((gap_start, y))
                in_gap = False

    if not gaps:
        return [(0, h)]

    # Build page regions from gaps
    pages: list[tuple[int, int]] = []
    prev_end = 0
    for gap_start, gap_end in gaps:
        mid = (gap_start + gap_end) // 2
        if mid - prev_end >= h * _MIN_PAGE_HEIGHT_RATIO:
            pages.append((prev_end, mid))
        prev_end = mid

    if h - prev_end >= h * _MIN_PAGE_HEIGHT_RATIO:
        pages.append((prev_end, h))

    if len(pages) <= 1:
        return [(0, h)]

    log.debug("detected %d pages in image", len(pages))
    return pages


# ── Public API ──────────────────────────────────────────────────────────────

def preprocess(image_path: Path) -> list[Path]:
    """Preprocess an image: fix orientation, deskew, denoise, normalize contrast.

    If multiple pages are detected, splits into separate files named
    {stem}_p1.png, {stem}_p2.png, etc.

    Returns list of output paths (one per page). Originals are preserved;
    processed images are written as PNG alongside the original.
    """
    img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if img is None:
        log.warning("could not read %s, skipping preprocessing", image_path.name)
        return [image_path]

    # Fix EXIF orientation
    img = _fix_orientation(img, image_path)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Deskew
    img, gray = _deskew(img, gray)

    # Denoise
    gray = _denoise(gray)

    # Contrast normalization
    gray = _normalize_contrast(gray)

    # Sharpen
    gray = _sharpen(gray)

    # Multi-page detection and split
    pages = _detect_pages(gray)

    output_dir = image_path.parent
    stem = image_path.stem
    outputs: list[Path] = []

    if len(pages) == 1:
        out_path = output_dir / f"{stem}.png"
        cv2.imwrite(str(out_path), gray)
        outputs.append(out_path)
    else:
        for i, (y_start, y_end) in enumerate(pages, 1):
            page_img = gray[y_start:y_end, :]
            out_path = output_dir / f"{stem}_p{i}.png"
            cv2.imwrite(str(out_path), page_img)
            outputs.append(out_path)

    log.info("preprocessed %s → %d output(s)", image_path.name, len(outputs))
    return outputs


def preprocess_all(image_paths: list[Path]) -> list[Path]:
    """Preprocess a batch of images. Returns flat list of all output paths."""
    all_outputs: list[Path] = []
    for p in image_paths:
        all_outputs.extend(preprocess(p))
    return all_outputs
