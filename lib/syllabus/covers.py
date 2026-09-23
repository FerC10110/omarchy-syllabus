"""Course covers copied to the cache, so they still show when the disk is unplugged.

A cover that comes from the web is the one thing here whose address is chosen by the
site on the other side of a link, so fetching one is treated as hostile: https only,
never an address on this machine or this network, few redirects, and an image whose
real size is read off its header before anything is asked to draw it."""
import hashlib
import http.client
import ipaddress
import os
import shutil
import socket
import ssl
import struct
import tempfile
import urllib.parse

from . import paths
from .scan import ext_of

MAX_REDIRECTS = 3
MAX_URL = 2048
MAX_SIDE = 10000
MAX_PIXELS = 40_000_000
IMAGE_EXTS = ("jpg", "jpeg", "png", "webp", "gif")


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
    """Where a thumbnail lands: its own hash, and the extension of the url without its
    query — but only one of the image extensions, never whatever the link asks for."""
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    ext = (ext_of(url.split("?", 1)[0]) or "").lower()
    return os.path.join(paths.covers_dir(), f"{digest}.{ext if ext in IMAGE_EXTS else 'jpg'}")


def _public(address):
    """True when an address is out on the internet: not this machine, not this network,
    not a link-local, multicast or reserved range."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_global and not (ip.is_private or ip.is_loopback or ip.is_link_local
                                 or ip.is_multicast or ip.is_reserved or ip.is_unspecified)


def resolve(host, port):
    """Every address a name answers with, or [] if any one of them is not public.

    All of them, not the first: a name that answers with one public and one private
    address would otherwise be a way to reach the private one."""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        return []
    found = [info[4][0] for info in infos]
    return found if found and all(_public(a) for a in found) else []


class _Pinned(http.client.HTTPSConnection):
    """https to the address that was checked, with the certificate and the SNI still
    belonging to the host name. Letting the socket layer resolve the name again would
    leave room for it to answer public once and private the second time."""

    def __init__(self, host, address, **rest):
        super().__init__(host, **rest)
        self._address = address

    def _create_connection(self, _address, timeout, source_address):
        return socket.create_connection((self._address, self.port), timeout, source_address)


def _jpeg_size(data):
    i, end = 2, len(data)
    while i + 9 < end:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0x01, 0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = int.from_bytes(data[i + 2:i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            return (int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big"))
        if length < 2:
            return None
        i += 2 + length
    return None


def _webp_size(data):
    tag = data[12:16]
    if tag == b"VP8X" and len(data) >= 30:
        return (int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1)
    if tag == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
        bits = int.from_bytes(data[21:25], "little")
        return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    if tag == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
        return (int.from_bytes(data[26:28], "little") & 0x3FFF,
                int.from_bytes(data[28:30], "little") & 0x3FFF)
    return None


def image_size(data):
    """(width, height) read from the header, or None when this is not an image format
    worth showing. A few hundred bytes of header decide it: what a file claims to be
    costs nothing, what it unpacks to is what fills the memory."""
    if not isinstance(data, (bytes, bytearray)) or len(data) < 24:
        return None
    data = bytes(data)
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", data[6:10])
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _webp_size(data)
    if data[:2] == b"\xff\xd8":
        return _jpeg_size(data)
    return None


def _sane(size):
    return size is not None and 0 < size[0] <= MAX_SIDE and 0 < size[1] <= MAX_SIDE \
        and size[0] * size[1] <= MAX_PIXELS


def fetch(url, max_bytes, timeout):
    """The bytes behind an https link, or b"".

    Every hop is checked before it is taken, not only the first: a redirect is the other
    side choosing the next address, and that is exactly the address worth refusing."""
    context = ssl.create_default_context()
    for _ in range(MAX_REDIRECTS + 1):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or len(url) > MAX_URL:
            return b""
        try:
            port = parts.port or 443
        except ValueError:
            return b""
        addresses = resolve(parts.hostname, port)
        if not addresses:
            return b""
        conn = _Pinned(parts.hostname, addresses[0], port=port, timeout=timeout, context=context)
        try:
            target = urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, ""))
            conn.request("GET", target, headers={"Accept": "image/*", "Connection": "close"})
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location") or ""
                if not location:
                    return b""
                url = urllib.parse.urljoin(url, location)
                continue
            if response.status != 200:
                return b""
            data = response.read(max_bytes + 1)
            return b"" if len(data) > max_bytes else data
        except (OSError, http.client.HTTPException, ssl.SSLError, ValueError):
            return b""
        finally:
            conn.close()
    return b""


def cache_remote(url, max_bytes=8 * 1024 * 1024, timeout=15, get=None):
    """Copy a remote thumbnail into the cover cache once and return its path, or "".

    Never raises: a cover is decoration, and the scan that asks for it must not fail
    because a thumbnail did not come."""
    get = fetch if get is None else get
    if not isinstance(url, str) or not url.startswith("https://") or len(url) > MAX_URL:
        return ""
    target = remote_path(url)
    if os.path.isfile(target):
        return target
    try:
        data = get(url, max_bytes, timeout)
    except Exception:
        return ""
    if not data or not _sane(image_size(data)):
        return ""
    folder = paths.covers_dir()
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=folder)
    try:
        with os.fdopen(fd, "wb") as out:
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
