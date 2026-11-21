from __future__ import annotations

import numpy as np

try:  # exact box filter in C; numpy can only do that slowly
    from PIL import Image
except ImportError:
    Image = None

# Frames handed to the sync engine are small; colour zones don't need detail,
# but every output pixel must be a true average of the area it covers.
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
    """Area-average a large frame down to width x height.

    Every output pixel is the mean of all screen pixels it covers, so fine
    detail like text averages out instead of flickering.
    """
    h, w = frame.shape[:2]
    if Image is not None and (h > height or w > width):
        rgb = np.ascontiguousarray(frame[:, :, :3])
        return np.asarray(Image.fromarray(rgb, "RGB").resize((width, height), Image.BOX))
    # fallback without Pillow: thin out huge frames first to keep it fast
    step = max(1, min(h // (height * 8), w // (width * 8)))
    if step > 1:
        frame = frame[::step, ::step]
        h, w = frame.shape[:2]
    fy = max(1, h // height)
    fx = max(1, w // width)
    if fx == 1 and fy == 1:
        return np.ascontiguousarray(frame[:, :, :3])
    h2, w2 = (h // fy) * fy, (w // fx) * fx
    block = frame[:h2, :w2, :3].astype(np.float32)
    small = block.reshape(h2 // fy, fy, w2 // fx, fx, 3).mean(axis=(1, 3))
    return small.astype(np.uint8)
