"""Security validation for user-uploaded design images.

Every uploaded file is validated by its *content* (never by the client's
file name, extension or Content-Type header) and re-encoded through Pillow
before storage. Re-encoding produces a fresh image containing only pixel
data, which strips EXIF/metadata, ICC payloads and any bytes appended after
the image stream, so nothing user-controlled other than the pixels ever
reaches the media storage.
"""

from io import BytesIO

from django.conf import settings
from PIL import Image

# Storage extension per allowed internal format.
_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


class ImageValidationError(Exception):
    """Raised when an uploaded image fails a security check.

    The message is user-facing.
    """


def validate_and_reencode(uploaded_file):
    """Validate one uploaded image and return ``(data, extension)``.

    ``data`` is the bytes of the re-encoded, sanitized copy; ``extension``
    is the storage extension matching its internal format. Raises
    ``ImageValidationError`` on any failure.

    Checks, in order:
    1. Size limit (settings.CUSTOM_DESIGN["MAX_IMAGE_BYTES"]).
    2. Decodes as a real image (full decode; rejects truncated/corrupt data,
       text files renamed to .png, polyglots, SVG, ...).
    3. Format allowlist (settings.CUSTOM_DESIGN["ALLOWED_FORMATS"]) - SVG and
       GIF can never pass (SVG is an XSS vector).
    4. Dimension limit (decompression-bomb guard).
    5. Re-encode through Pillow into a clean buffer (metadata stripping).
    """
    conf = settings.CUSTOM_DESIGN

    if uploaded_file.size > conf["MAX_IMAGE_BYTES"]:
        max_mb = conf["MAX_IMAGE_BYTES"] / (1024 * 1024)
        raise ImageValidationError(f"Each image must be at most {max_mb:g} MB.")

    raw = uploaded_file.read()
    try:
        image = Image.open(BytesIO(raw))
        image.load()  # full decode - verify() alone would skip pixel data
    except Exception:
        # Pillow raises DecompressionBombError / UnidentifiedImageError /
        # OSError / ValueError here - all collapsed into one generic 400.
        raise ImageValidationError("The uploaded file is not a valid image.")

    if image.format not in conf["ALLOWED_FORMATS"]:
        allowed = ", ".join(conf["ALLOWED_FORMATS"]).lower()
        raise ImageValidationError(
            f"Only {allowed} images are accepted (the file's real content "
            "must be an image, not just its name)."
        )

    max_dimension = conf["MAX_IMAGE_DIMENSION"]
    if image.width > max_dimension or image.height > max_dimension:
        raise ImageValidationError(
            f"Image dimensions must not exceed {max_dimension}x{max_dimension} pixels."
        )

    # JPEG/WEBP encoders accept only a subset of color modes.
    if image.format == "JPEG" and image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    elif image.format == "WEBP" and image.mode not in ("RGB", "RGBA", "L"):
        image = image.convert("RGB")

    buffer = BytesIO()
    try:
        # Fresh encoder instance: no icc_profile/EXIF/xmp kwargs are passed,
        # so no metadata is carried over into the output.
        image.save(buffer, format=image.format)
    except Exception:
        raise ImageValidationError("The image could not be processed.")

    return buffer.getvalue(), _EXTENSIONS[image.format]