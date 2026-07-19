"""Tests for photos.py: normalizing an uploaded image into the (b64, media_type)
pair vcard.set_photo writes. Pure function, no FastAPI/DAV involved -- images are
generated in-test with Pillow so nothing depends on fixture binaries."""

import base64
import io

import pytest
from PIL import Image

from peopledb.photos import MAX_UPLOAD_BYTES, PhotoError, process_upload


def _encode(img: Image.Image, fmt: str, **kwargs) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def _decoded(b64: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(b64)))


def test_accepts_small_jpeg_and_returns_b64_and_media_type():
    data = _encode(Image.new("RGB", (100, 100), "red"), "JPEG")
    b64, media_type = process_upload(data)
    assert media_type == "image/jpeg"
    decoded = base64.b64decode(b64)
    assert decoded  # non-empty
    img = _decoded(b64)
    assert img.format == "JPEG"


def test_accepts_png():
    data = _encode(Image.new("RGB", (100, 100), "blue"), "PNG")
    b64, media_type = process_upload(data)
    assert media_type == "image/jpeg"  # always re-encoded to JPEG
    assert _decoded(b64).format == "JPEG"


def test_downscales_longest_side_to_512():
    data = _encode(Image.new("RGB", (2000, 1000), "green"), "JPEG")
    b64, _ = process_upload(data)
    img = _decoded(b64)
    assert max(img.size) <= 512
    assert img.size[0] / img.size[1] == pytest.approx(2000 / 1000, rel=0.02)


def test_does_not_upscale_small_images():
    data = _encode(Image.new("RGB", (50, 40), "green"), "JPEG")
    b64, _ = process_upload(data)
    img = _decoded(b64)
    assert img.size == (50, 40)


def test_flattens_alpha_onto_white():
    img = Image.new("RGBA", (10, 10), (0, 0, 0, 0))  # fully transparent
    data = _encode(img, "PNG")
    b64, _ = process_upload(data)
    decoded = _decoded(b64).convert("RGB")
    assert decoded.getpixel((5, 5)) == (255, 255, 255)


def test_exif_orientation_is_applied():
    img = Image.new("RGB", (100, 60), "red")
    exif = img.getexif()
    exif[0x0112] = 6  # Orientation: rotate 270 (i.e. displayed rotated 90 CW)
    data = _encode(img, "JPEG", exif=exif)
    b64, _ = process_upload(data)
    img_out = _decoded(b64)
    # After exif_transpose, a 100x60 image tagged orientation=6 becomes 60x100.
    assert img_out.size == (60, 100)


def test_rejects_oversize_upload():
    data = b"x" * (MAX_UPLOAD_BYTES + 1)
    with pytest.raises(PhotoError):
        process_upload(data)


def test_rejects_corrupt_image_data():
    with pytest.raises(PhotoError):
        process_upload(b"not-an-image-at-all")


def test_rejects_non_jpeg_png_format():
    data = _encode(Image.new("RGB", (10, 10), "red"), "BMP")
    with pytest.raises(PhotoError):
        process_upload(data)


def test_rejects_gif():
    data = _encode(Image.new("RGB", (10, 10), "red"), "GIF")
    with pytest.raises(PhotoError):
        process_upload(data)


def test_non_accepted_format_is_rejected_without_decoding_pixels(monkeypatch):
    """The format allowlist must be checked from the lazily-parsed header,
    before any pixel decode -- proven here by making Image.load explode if
    it's ever called, then confirming a BMP (rejected format) is still
    turned away with the ordinary PhotoError, not that explosion."""
    from PIL import ImageFile

    def _boom(self, *a, **kw):
        raise AssertionError("pixel data was decoded for a format that should have been rejected first")

    monkeypatch.setattr(ImageFile.ImageFile, "load", _boom)
    data = _encode(Image.new("RGB", (10, 10), "red"), "BMP")
    with pytest.raises(PhotoError, match="JPEG or PNG"):
        process_upload(data)


def test_rejects_decompression_bomb_as_photo_error(monkeypatch):
    """A pixel count past Pillow's hard 2x-MAX_IMAGE_PIXELS limit raises
    DecompressionBombError from within Image.open itself; it must surface as
    PhotoError (400-ish, user-facing), never bubble up as a bare exception."""
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    data = _encode(Image.new("RGB", (100, 100), "red"), "PNG")  # 10_000 px > 2*100
    with pytest.raises(PhotoError, match="too large"):
        process_upload(data)


def test_rejects_decompression_bomb_warning_as_error(monkeypatch):
    """Between MAX_IMAGE_PIXELS and 2x it, Pillow only issues a
    DecompressionBombWarning -- but a deployment that configures warnings as
    errors turns that into a real exception at the same call site, which must
    also map to PhotoError rather than an unhandled warning-turned-exception."""
    import warnings

    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    try:
        data = _encode(Image.new("RGB", (14, 14), "red"), "PNG")  # 196 px, between 100 and 200
        with pytest.raises(PhotoError, match="too large"):
            process_upload(data)
    finally:
        warnings.resetwarnings()
