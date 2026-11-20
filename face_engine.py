"""Face encoding and matching helpers used by the Flask application."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np


MODEL = "hog"
TOLERANCE = 0.5


def _face_recognition_module():
    try:
        import face_recognition
    except ImportError as exc:
        raise RuntimeError(
            "Face recognition is unavailable. Install the packages in requirements.txt."
        ) from exc
    return face_recognition


def encode_photo(image_path: Path) -> list[float]:
    """Encode a photo only when it contains exactly one detectable face."""
    face_recognition = _face_recognition_module()
    image = face_recognition.load_image_file(str(image_path))
    boxes = face_recognition.face_locations(image, model=MODEL)
    if len(boxes) != 1:
        raise ValueError(
            f"{image_path.name}: expected one face, found {len(boxes)}."
        )
    encodings = face_recognition.face_encodings(image, boxes)
    if len(encodings) != 1:
        raise ValueError(f"{image_path.name}: could not generate a face encoding.")
    return encodings[0].tolist()


def build_encodings(
    students: list[dict[str, Any]], project_root: Path
) -> tuple[list[dict[str, Any]], list[str]]:
    """Create one encoding per student and retain failures as visible warnings."""
    encoded: list[dict[str, Any]] = []
    issues: list[str] = []
    for student in students:
        photo = str(student.get("photo") or "")
        if not photo:
            issues.append(f"{student['name']}: no photo assigned")
            continue
        if photo.startswith("Hostel Student/"):
            image_path = project_root / "Hostel Student" / photo.split("/", 1)[1]
        elif photo.startswith("static/uploads/"):
            image_path = project_root / photo
        else:
            issues.append(f"{student['name']}: unsupported photo path")
            continue
        if not image_path.is_file():
            issues.append(f"{student['name']}: photo is missing ({image_path.name})")
            continue
        try:
            encoding = encode_photo(image_path)
        except (OSError, RuntimeError, ValueError) as exc:
            issues.append(str(exc))
            continue
        encoded.append({"student_id": student["id"], "encoding": encoding})
    return encoded, issues


def save_encodings(path: Path, encodings: list[dict[str, Any]]) -> None:
    """Atomically persist the cache so interrupted refreshes don't corrupt it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "encodings": encodings}
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(payload, temporary, separators=(",", ":"))
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def recognize_image(
    image_rgb: np.ndarray,
    stored_encodings: list[dict[str, Any]],
    tolerance: float = TOLERANCE,
) -> list[dict[str, Any]]:
    """Return each detected face, its best match and an approximate match score."""
    face_recognition = _face_recognition_module()
    boxes = face_recognition.face_locations(image_rgb, model=MODEL)
    observed = face_recognition.face_encodings(image_rgb, boxes)
    known_encodings = [
        np.asarray(item["encoding"], dtype=float) for item in stored_encodings
    ]
    results: list[dict[str, Any]] = []
    for box, encoding in zip(boxes, observed):
        best_index: int | None = None
        best_distance: float | None = None
        for index, known in enumerate(known_encodings):
            if known.shape != encoding.shape:
                continue
            distance = float(np.linalg.norm(known - encoding))
            if best_distance is None or distance < best_distance:
                best_index = index
                best_distance = distance
        matched = best_distance is not None and best_distance <= tolerance
        match_score = (
            round(max(0.0, min(100.0, (1.0 - best_distance / tolerance) * 100)), 1)
            if best_distance is not None
            else 0.0
        )
        results.append(
            {
                "box": tuple(int(coordinate) for coordinate in box),
                "student_id": (
                    stored_encodings[best_index]["student_id"]
                    if matched and best_index is not None
                    else None
                ),
                "distance": best_distance,
                "confidence": match_score,
            }
        )
    return results
