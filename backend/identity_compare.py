"""
Shared profile vs live face scoring for verify_face and proctoring.

Uses face-aligned grayscale (fixed size), mild illumination flattening, CLAHE,
then histogram correlation on (1) full face and (2) periocular (eyes + brows).

Histogram-only matching is sensitive to lighting; we add:
  - same-size aligned crops so profile vs webcam are comparable;
  - retinex-style local normalization before CLAHE;
  - practical default thresholds (tunable via env);
  - optional ORB descriptor agreement as a secondary pass when histograms are borderline.
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

import cv2
import numpy as np

_FACE_ALIGN = 128


def _clahe_gray(gray: np.ndarray) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def _largest_face_rect(gray: np.ndarray, *, is_profile: bool) -> Optional[Tuple[int, int, int, int]]:
    scale = 1.05 if is_profile else 1.08
    neighbors = 3 if is_profile else 4
    min_s = (40, 40) if is_profile else (48, 48)
    path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    path_alt = cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml"
    cascade = cv2.CascadeClassifier(path)
    cascade_alt = cv2.CascadeClassifier(path_alt)
    faces = cascade.detectMultiScale(gray, scaleFactor=scale, minNeighbors=neighbors, minSize=min_s)
    if len(faces) == 0:
        faces = cascade_alt.detectMultiScale(gray, scaleFactor=scale, minNeighbors=neighbors, minSize=min_s)
    if len(faces) == 0:
        return None
    faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
    x, y, w, h = faces[0]
    return int(x), int(y), int(w), int(h)


def _align_face_gray(bgr: np.ndarray, *, is_profile: bool) -> Optional[np.ndarray]:
    """
    Largest frontal face → margin crop → resize to _FACE_ALIGN² →
    divide by blurred luminance (reduces global lighting gap) → CLAHE.
    """
    if bgr is None or bgr.size == 0:
        return None
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    rect = _largest_face_rect(gray, is_profile=is_profile)
    if rect is None:
        return None
    x, y, w, h = rect
    mh, mw = gray.shape[:2]
    pad_x = max(1, int(0.1 * w))
    pad_y = max(1, int(0.1 * h))
    x0 = max(0, x - pad_x)
    y0 = max(0, y - pad_y)
    x1 = min(mw, x + w + pad_x)
    y1 = min(mh, y + h + pad_y)
    crop = gray[y0:y1, x0:x1]
    if crop.size < 400 or crop.shape[0] < 20 or crop.shape[1] < 20:
        return None
    aligned = cv2.resize(crop, (_FACE_ALIGN, _FACE_ALIGN), interpolation=cv2.INTER_AREA)
    blur = cv2.GaussianBlur(aligned, (0, 0), sigmaX=9, sigmaY=9)
    blur = np.maximum(blur.astype(np.float32), 4.0)
    norm = aligned.astype(np.float32) / blur
    norm = np.clip(norm * 88.0, 0, 255).astype(np.uint8)
    return _clahe_gray(norm)


def _normalized_hist(roi_gray: np.ndarray) -> Optional[np.ndarray]:
    if roi_gray is None or roi_gray.size < 80:
        return None
    hist = cv2.calcHist([roi_gray], [0], None, [256], [0, 256])
    cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
    return hist


def extract_face_and_periocular_histograms(
    bgr: np.ndarray, *, is_profile: bool
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """
    Returns (face_hist, periocular_hist) from aligned 128×128 face.
    """
    aligned = _align_face_gray(bgr, is_profile=is_profile)
    if aligned is None:
        return None, None
    face_hist = _normalized_hist(aligned)
    if face_hist is None:
        return None, None
    eye_h = max(int(aligned.shape[0] * 0.45), 28)
    if aligned.shape[0] < 56:
        return face_hist, None
    peri = aligned[0:eye_h, :]
    eye_hist = _normalized_hist(peri)
    return face_hist, eye_hist


def _orb_support_score(profile_bgr: np.ndarray, live_bgr: np.ndarray) -> float:
    """0..~1 — texture / keypoint agreement on aligned faces (helps same-person, different light)."""
    g1 = _align_face_gray(profile_bgr, is_profile=True)
    g2 = _align_face_gray(live_bgr, is_profile=False)
    if g1 is None or g2 is None:
        return 0.0
    orb = cv2.ORB_create(280, scaleFactor=1.2, nlevels=5, edgeThreshold=12)
    kp1, d1 = orb.detectAndCompute(g1, None)
    kp2, d2 = orb.detectAndCompute(g2, None)
    if d1 is None or d2 is None or len(kp1) < 6 or len(kp2) < 6:
        return 0.0
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    raw = bf.knnMatch(d1, d2, k=2)
    good = 0
    for pair in raw:
        if len(pair) != 2:
            continue
        m, n = pair
        if m.distance < 0.78 * n.distance:
            good += 1
    denom = max(min(len(kp1), len(kp2)), 1)
    return float(good) / float(denom)


def compare_histogram_identity(
    profile_bgr: np.ndarray,
    live_bgr: np.ndarray,
    *,
    mode: str = "continuous",
) -> Tuple[bool, str, float, Optional[float], Optional[float], str]:
    """
    Match profile still vs live frame.
    Returns: ok, message, face_corr, eye_corr|None, combined|None, code

    code is one of: MATCH, NO_FACE_PROFILE, NO_FACE_LIVE, FACE_MISMATCH

    ``mode``:
      - ``"verify"`` — one-shot login / gate (stricter; no ORB relaxation).
      - ``"continuous"`` — during interview drift / lighting (relaxed ORB path allowed).

    Env for **continuous** (defaults in parentheses):
      FACE_MATCH_MIN_CORREL (0.38), FACE_MATCH_EYE_MIN_CORREL (0.32),
      FACE_MATCH_COMBINED_MIN (0.40), FACE_MATCH_ORB_MIN (0.10)

    Env for **verify** (defaults stricter):
      FACE_VERIFY_MIN_CORREL (0.48), FACE_VERIFY_EYE_MIN_CORREL (0.42),
      FACE_VERIFY_COMBINED_MIN (0.50)
    """
    verify = (mode or "continuous").lower() == "verify"

    pf, pe = extract_face_and_periocular_histograms(profile_bgr, is_profile=True)
    lf, le = extract_face_and_periocular_histograms(live_bgr, is_profile=False)

    if pf is None:
        return False, "No clear face found in your profile photo.", 0.0, None, None, "NO_FACE_PROFILE"
    if lf is None:
        return False, "No clear face detected in the camera image.", 0.0, None, None, "NO_FACE_LIVE"

    fc = float(cv2.compareHist(pf, lf, cv2.HISTCMP_CORREL))

    if verify:
        face_min = float(os.environ.get("FACE_VERIFY_MIN_CORREL", "0.48"))
        combined_min = float(os.environ.get("FACE_VERIFY_COMBINED_MIN", "0.50"))
        eye_min = float(os.environ.get("FACE_VERIFY_EYE_MIN_CORREL", "0.42"))
        orb_min = 1.0  # disables ORB fallback branches below
    else:
        face_min = float(os.environ.get("FACE_MATCH_MIN_CORREL", "0.38"))
        combined_min = float(os.environ.get("FACE_MATCH_COMBINED_MIN", "0.40"))
        eye_min = float(os.environ.get("FACE_MATCH_EYE_MIN_CORREL", "0.32"))
        orb_min = float(os.environ.get("FACE_MATCH_ORB_MIN", "0.10"))

    ee: Optional[float] = None
    combined: Optional[float] = None

    if pe is not None and le is not None:
        ee = float(cv2.compareHist(pe, le, cv2.HISTCMP_CORREL))
        combined = 0.38 * fc + 0.62 * ee
        strict = fc >= face_min and ee >= eye_min and combined >= combined_min
        if strict:
            return True, "Identity verified.", fc, ee, combined, "MATCH"

        if not verify:
            orb_s = _orb_support_score(profile_bgr, live_bgr)
            relaxed = (
                combined is not None
                and combined >= (combined_min - 0.04)
                and fc >= (face_min - 0.06)
                and ee >= (eye_min - 0.06)
                and orb_s >= orb_min
            )
            if relaxed:
                return True, "Identity verified.", fc, ee, combined, "MATCH"

        return (
            False,
            f"Face and eye-region do not match your profile (face={fc:.2f}, eyes={ee:.2f}). "
            f"Use the same person as your account photo, face the camera straight-on, and avoid strong backlight or heavy shadows.",
            fc,
            ee,
            combined,
            "FACE_MISMATCH",
        )

    combined = fc
    ok = fc >= max(face_min, combined_min) - (0.0 if verify else 0.02)
    if ok:
        return True, "Identity verified (face only; eye region too small).", fc, None, fc, "MATCH"

    if not verify:
        orb_s = _orb_support_score(profile_bgr, live_bgr)
        if fc >= (face_min - 0.08) and orb_s >= orb_min:
            return True, "Identity verified.", fc, None, fc, "MATCH"

    return (
        False,
        f"Face does not match your profile photo (similarity {fc:.2f}). "
        "Use the same person as on your account, face the camera with even lighting.",
        fc,
        None,
        fc,
        "FACE_MISMATCH",
    )
