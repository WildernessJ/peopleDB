"""Normalize an uploaded contact photo into the (b64, media_type) pair
vcard.set_photo writes. Pillow-based; deliberately narrow (issue #11):
JPEG/PNG in, always re-encoded JPEG out, no cropping UI, no original-
resolution preservation (see specs/2026-07-13-photo-upload.md)."""

from __future__ import annotations

import base64
import io

from PIL import Image, ImageOps

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_DIMENSION = 512
JPEG_QUALITY = 85
_ACCEPTED_FORMATS = ("JPEG", "PNG")


class PhotoError(Exception):
    """Rejected or undecodable photo upload; message is user-facing (rendered
    in the form's error banner, never a 500)."""


def process_upload(data: bytes) -> tuple[str, str]:
    """Validate and normalize an uploaded image. Returns (b64, media_type);
    media_type is always "image/jpeg" since output is always re-encoded JPEG.
    Raises PhotoError for oversize/wrong-type/corrupt input."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise PhotoError("Photo is too large (max 10 MB).")

    try:
        image = Image.open(io.BytesIO(data))
        # Image.open only parses the header (lazy) -- check the format allowlist
        # before doing any pixel work (.load()) so a non-JPEG/PNG file never gets
        # decoded at all, and before Pillow's own size check so an oversize
        # decompression-bomb file of a rejected format is turned away just as
        # cheaply as everything else.
        if image.format not in _ACCEPTED_FORMATS:
            raise PhotoError("Photo must be a JPEG or PNG image.")
        image.load()
    except PhotoError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        # DecompressionBombError is Pillow's own raise past 2x MAX_IMAGE_PIXELS;
        # DecompressionBombWarning is normally just a warning between the limit
        # and 2x it, but some deployments configure warnings-as-errors, in which
        # case Python raises it as an exception too -- map both the same way.
        raise PhotoError("Photo is too large (too many pixels).") from exc
    except Exception as exc:
        raise PhotoError("Photo file is corrupt or not a recognizable image.") from exc

    image = ImageOps.exif_transpose(image) or image

    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        flattened = Image.new("RGB", rgba.size, (255, 255, 255))
        flattened.paste(rgba, mask=rgba.split()[-1])
        image = flattened
    else:
        image = image.convert("RGB")

    image.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)

    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return base64.b64encode(buf.getvalue()).decode("ascii"), "image/jpeg"
