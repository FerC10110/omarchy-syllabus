"""Course covers copied to the cache, so they still show when the disk is unplugged."""
import hashlib
import os
import shutil
import tempfile

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
