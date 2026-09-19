"""Video durations, read with ffprobe."""
import os
import subprocess


class ProbeError(Exception):
    pass


def ffprobe_bin():
    return os.environ.get("SYLLABUS_FFPROBE") or "ffprobe"


def probe_duration(path, timeout=30):
    """Seconds of video in `path`. Raises ProbeError when ffprobe cannot tell."""
    argv = [ffprobe_bin(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]
    try:
        # errors="replace": ffprobe echoes file names, which need not be UTF-8.
        result = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout)
    except FileNotFoundError:
        raise ProbeError("ffprobe is not installed")
    except OSError as e:  # e.g. not executable: this file's error, never the whole scan's
        raise ProbeError(f"ffprobe could not run: {e.strerror or e}")
    except subprocess.TimeoutExpired:
        raise ProbeError("ffprobe took too long")
    if result.returncode != 0:
        lines = (result.stderr or "").strip().splitlines()
        raise ProbeError(lines[-1] if lines else "ffprobe failed")
    lines = (result.stdout or "").strip().splitlines()
    try:
        value = float(lines[0])
    except (IndexError, ValueError):
        raise ProbeError("no duration")
    if value != value or value < 0:
        raise ProbeError("no duration")
    return value
