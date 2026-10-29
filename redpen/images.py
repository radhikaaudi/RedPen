"""Prepare uploaded answer-sheet photos for the vision model."""

import base64
import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SIDE = 1800  # enough for handwriting, keeps vision tokens and upload size down


class ImageError(ValueError):
    pass


def to_data_url(raw: bytes) -> str:
    """Fix phone-camera rotation, downscale, and return a JPEG data URL."""
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise ImageError("Could not read image. Please upload JPG or PNG photos.") from e
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
