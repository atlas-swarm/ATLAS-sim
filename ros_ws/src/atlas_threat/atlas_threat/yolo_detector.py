"""YOLOv8n-based object detector for the ATLAS threat pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

import numpy as np

_ALLOWED_CLASSES = {"person", "car", "truck", "bus", "motorcycle"}
_CONFIDENCE_THRESHOLD = 0.4


@dataclass
class Detection:
    object_type: str
    confidence: float
    bounding_box: tuple[int, int, int, int]  # x1, y1, x2, y2


class YoloDetector:
    def __init__(self, model_path: str = "yolov8n.pt") -> None:
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise ImportError(
                "ultralytics is required for YOLO inference. Install it with `pip install ultralytics`."
            ) from exc

        self._model = YOLO(model_path)

    def detect(self, frame: np.ndarray) -> list[Detection]:
        """Run YOLOv8n inference and return filtered detections."""
        results = self._model(frame, verbose=False)
        detections: list[Detection] = []
        for result in results:
            for box in result.boxes:
                confidence = float(box.conf[0])
                if confidence < _CONFIDENCE_THRESHOLD:
                    continue
                class_name = result.names[int(box.cls[0])]
                if class_name not in _ALLOWED_CLASSES:
                    continue
                x1, y1, x2, y2 = (int(v) for v in box.xyxy[0])
                detections.append(
                    Detection(
                        object_type=class_name,
                        confidence=confidence,
                        bounding_box=(x1, y1, x2, y2),
                    )
                )
        return detections


def adapt_camera_frame(camera_frame: Union[dict, np.ndarray]) -> np.ndarray:
    """Convert a camera frame dict to a numpy array, or pass ndarray through unchanged."""
    if isinstance(camera_frame, np.ndarray):
        return camera_frame

    resolution = camera_frame.get("resolution", (640, 480))
    width, height = resolution
    pixels = camera_frame.get("pixels")

    if pixels is None:
        return np.zeros((height, width, 3), dtype=np.uint8)

    return np.array(pixels, dtype=np.uint8).reshape((height, width, 3))


if __name__ == "__main__":
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    detector = YoloDetector()
    detections = detector.detect(dummy_frame)
    print(f"Detections on black frame: {detections}")

    dict_frame: dict = {
        "pixels": dummy_frame.flatten().tolist(),
        "resolution": (640, 480),
    }
    adapted = adapt_camera_frame(dict_frame)
    print(f"adapt_camera_frame (dict with pixels) shape: {adapted.shape}")

    no_pixels_frame: dict = {"resolution": (320, 240)}
    black = adapt_camera_frame(no_pixels_frame)
    print(f"adapt_camera_frame (no pixels fallback) shape: {black.shape}")

    passthrough = adapt_camera_frame(dummy_frame)
    print(f"adapt_camera_frame (ndarray passthrough) shape: {passthrough.shape}")
