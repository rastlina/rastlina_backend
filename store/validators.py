from django.core.exceptions import ValidationError

MAX_VIDEO_BYTES = 20 * 1024 * 1024


def validate_mp4_upload(value):
    """Accept MP4 containers up to 20 MB; preserve the upload stream position."""
    if value.size > MAX_VIDEO_BYTES:
        raise ValidationError("Please upload an MP4 smaller than 20 MB.")
    try:
        stream = value.file
        position = stream.tell()
        try:
            stream.seek(0)
            header = stream.read(64)
        finally:
            stream.seek(position)
    except (OSError, ValueError) as exc:
        raise ValidationError("The video could not be read. Please upload it again.") from exc
    if len(header) < 12 or header[4:8] != b"ftyp":
        raise ValidationError("Please upload a valid MP4 video, not a renamed file.")

