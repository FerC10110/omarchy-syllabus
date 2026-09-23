"""mpv: start it with the companion script, or hand the file to the one already running."""
import json
import os
import socket
import subprocess

from . import paths
from .errors import PLAYER, SyllabusError

QUALITY_HEIGHT = {"720p": 720, "1080p": 1080, "best": 0}


def format_selector(web):
    """yt-dlp's format for a link: the quality cap, and the dubbed audio when one is asked
    for. The chain always ends without the language, so a video that has no dub plays with
    its original audio instead of failing. The audio cannot be switched later: ytdl_hook
    exposes a link's tracks without their language, so this is the one chance to pick."""
    height = QUALITY_HEIGHT.get(web.get("quality"), 1080)
    language = str(web.get("audioLanguage") or "").strip()
    if height:
        plain = f"bv*[height<={height}]+ba/b[height<={height}]"
        return f"bv*[height<={height}]+ba[language^={language}]/{plain}" if language else plain
    return f"bv*+ba[language^={language}]/b" if language else ""


def escape(value):
    """mpv's escape inside a comma-separated list of values: %<bytes>%<value>."""
    return f"%{len(value.encode('utf-8'))}%{value}" if ("," in value or "%" in value) else value


def web_options(config, password=""):
    """What a streamed link needs, as (name, value) pairs: they go on the command line as
    --name=value and into `loadfile` as name=value. Subtitles are the ones the site
    publishes with the video; nothing is looked up anywhere else."""
    web = config.get("web") or {}
    options, raw = [], []
    selector = format_selector(web)
    if selector:
        options.append(("ytdl-format", selector))
    languages = [l for l in (web.get("subtitleLanguages") or []) if isinstance(l, str) and l]
    if languages:
        options.append(("slang", ",".join(languages)))
        raw.append("sub-langs=" + escape(",".join(languages)))
        if web.get("autoSubtitles"):
            raw.append("write-auto-subs=")
    else:
        options.append(("sid", "no"))
    if raw:
        options.append(("ytdl-raw-options", ",".join(raw)))
    # The password is kept apart: everything in `options` may end up on a command line,
    # and a command line is readable by every process on the machine through /proc.
    return options, (["video-password=" + escape(password)] if password else [])


def _long(value):
    """mpv's length-prefixed form, used unconditionally: a configuration line otherwise
    ends at a `#` or a space, and a password is allowed to contain both."""
    return f"%{len(value.encode('utf-8'))}%{value}"


def with_secret(options, secret):
    """The options with the secret raw ones folded in, for the IPC socket: that socket
    lives in this session's own runtime directory, which no other user can enter."""
    if not secret:
        return list(options)
    out, folded = [], False
    for key, value in options:
        if key == "ytdl-raw-options":
            out.append((key, ",".join([value] + list(secret))))
            folded = True
        else:
            out.append((key, value))
    if not folded:
        out.append(("ytdl-raw-options", ",".join(secret)))
    return out


def secret_include(secret):
    """An unnamed file with the options that must not appear in a command line, or None.

    It exists only as a file descriptor: nothing in the filesystem points at it and it is
    gone as soon as mpv and this process close it. mpv reads it back through /dev/fd."""
    if not secret:
        return None
    fd = os.memfd_create("syllabus-mpv")
    os.write(fd, ("ytdl-raw-options-append=" + _long(",".join(secret)) + "\n").encode("utf-8"))
    os.lseek(fd, 0, os.SEEK_SET)
    return fd


def file_options(start, options):
    """The per-file options `loadfile` takes. mpv reverts them when the file is unloaded,
    so a disk video opened afterwards inherits nothing."""
    return ",".join([f"start={float(start):.3f}"] + [f"{key}={escape(value)}" for key, value in options])


def build_argv(config, media_path, start, sock, options=(), secret_fd=None):
    player = config["player"]
    return ([player["command"],
             "--force-window=immediate",
             f"--input-ipc-server={sock}",
             f"--start={float(start):.3f}",
             # state.json is the only source of positions; mpv's watch_later would fight it.
             "--resume-playback=no",
             "--save-position-on-quit=no",
             f"--script={paths.LUA_PATH}",
             # One option per flag: --script-opts would split on the commas some folders have.
             f"--script-opt=syllabus-bin={paths.BIN_PATH}",
             f"--script-opt=syllabus-report={int(config['reportSeconds'])}"]
            + [f"--{key}={value}" for key, value in options]
            # After the options above, so its append lands on top of ytdl-raw-options.
            + ([] if secret_fd is None else [f"--include=/dev/fd/{secret_fd}"])
            + [str(arg) for arg in player.get("args", [])]
            + ["--", media_path])


def request(sock_path, command, timeout=2.0):
    """Send one JSON IPC command and return mpv's reply, skipping the events it interleaves."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(sock_path)
        s.sendall((json.dumps({"command": command, "request_id": 1}) + "\n").encode("utf-8"))
        buffer = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                raise ConnectionError("mpv closed the connection")
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if isinstance(message, dict) and message.get("request_id") == 1 and "error" in message:
                    return message


def is_alive(sock_path):
    """True when an mpv answers on the socket; False when none is there (no socket,
    or one nobody listens on). Anything else is an mpv that is there but did not
    answer in time: starting a second one beside it would be wrong."""
    try:
        request(sock_path, ["get_property", "pid"], timeout=1.0)
        return True
    except (FileNotFoundError, ConnectionRefusedError):
        return False
    except TimeoutError:
        raise SyllabusError("mpv is busy", PLAYER)
    except OSError as e:
        raise SyllabusError(f"mpv did not answer: {e}", PLAYER)


def play(config, media_path, start, sock=None, spawn=subprocess.Popen, options=(), secret=()):
    sock = sock or paths.socket_path()
    if is_alive(sock):
        try:
            reply = request(sock, ["loadfile", media_path, "replace", -1,
                                   file_options(start, with_secret(options, secret))])
        except OSError as e:
            raise SyllabusError(f"mpv did not answer: {e}", PLAYER)
        if reply.get("error") != "success":
            raise SyllabusError(f"mpv could not open the file: {reply.get('error')}", PLAYER)
        return "loaded"
    try:
        os.unlink(sock)
    except OSError:
        pass
    os.makedirs(os.path.dirname(sock), exist_ok=True)
    fd = secret_include(secret)
    try:
        spawn(build_argv(config, media_path, start, sock, options, fd), stdin=subprocess.DEVNULL,
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
              close_fds=True, pass_fds=() if fd is None else (fd,))
    except OSError as e:
        raise SyllabusError(f"Could not start {config['player']['command']}: {e.strerror or e}", PLAYER)
    finally:
        if fd is not None:
            os.close(fd)
    return "started"


def current(sock=None):
    """(path, seconds) of what the running mpv is playing."""
    sock = sock or paths.socket_path()
    try:
        path = request(sock, ["get_property", "path"]).get("data")
        pos = request(sock, ["get_property", "time-pos"]).get("data")
    except OSError:
        raise SyllabusError("mpv is not playing anything", PLAYER)
    if not isinstance(path, str) or not path:
        raise SyllabusError("mpv is not playing anything", PLAYER)
    return path, float(pos or 0)
