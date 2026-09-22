"""Course covers copied to the cache, so they still show when the disk is unplugged."""
import hashlib
import os
import shutil
import tempfile
import urllib.request

from . import paths
from .scan import ext_of


def cached_path(source):
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]
    return os.path.join(paths.covers_dir(), f"{digest}.{ext_of(source) or 'img'}")


def cache_cover(source):
    """Copy the image into the cache once and return the cached path.

    Copies through a uniquely-named temp file in the same folder, fsynced before
    the atomic rename, so a crash or a concurrent call for the same source never
    leaves a half-written or corrupted file at `target`."""
    target = cached_path(source)
    if not os.path.isfile(target):
        folder = paths.covers_dir()
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=folder)
        try:
            with os.fdopen(fd, "wb") as out, open(source, "rb") as src:
                shutil.copyfileobj(src, out)
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    return target


def remote_path(url):
    """Where a thumbnail lands: its own hash, and the extension of the url without its query."""
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    ext = ext_of(url.split("?", 1)[0]) or "jpg"
    return os.path.join(paths.covers_dir(), f"{digest}.{ext}")


def cache_remote(url, max_bytes=8 * 1024 * 1024, timeout=15, opener=urllib.request.urlopen):
    """Copy a remote thumbnail into the cover cache once and return its path, or "".

    Never raises: a cover is decoration, and the scan that asks for it must not
    fail because a thumbnail did not come."""
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return ""
    target = remote_path(url)
    if os.path.isfile(target):
        return target
    folder = paths.covers_dir()
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=folder)
    try:
        with os.fdopen(fd, "wb") as out:
            with opener(url, timeout=timeout) as response:
                data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise OSError("the thumbnail is too big")
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, target)
        return target
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return ""
