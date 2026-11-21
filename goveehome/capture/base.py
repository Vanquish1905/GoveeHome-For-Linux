from __future__ import annotations

import numpy as np

# Frames handed to the sync engine are small; colour zones don't need detail.
FRAME_WIDTH = 160
FRAME_HEIGHT = 90


class CaptureError(Exception):
    pass


class CaptureBackend:
    """Produces small RGB frames (H x W x 3, uint8) of the screen."""

    id = "base"
    label = "Base"

    def open(self) -> None:
        pass

    def grab(self) -> np.ndarray:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()


def downscale(frame: np.ndarray, width: int = FRAME_WIDTH, height: int = FRAME_HEIGHT) -> np.ndarray:
    """Area-average a large frame down to roughly width x height."""
    h, w = frame.shape[:2]
    fy = max(1, h // height)
    fx = max(1, w // width)
    if fx == 1 and fy == 1:
        return np.ascontiguousarray(frame[:, :, :3])
    h2, w2 = (h // fy) * fy, (w // fx) * fx
    cropped = frame[:h2, :w2, :3].astype(np.uint32)
    small = cropped.reshape(h2 // fy, fy, w2 // fx, fx, 3).mean(axis=(1, 3))
    return small.astype(np.uint8)
