"""mpv: start it with the companion script, or hand the file to the one already running."""
import json
import os
import socket
import subprocess

from . import paths
from .errors import PLAYER, SyllabusError


def build_argv(config, media_path, start, sock):
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


def play(config, media_path, start, sock=None, spawn=subprocess.Popen):
    sock = sock or paths.socket_path()
    if is_alive(sock):
        try:
            reply = request(sock, ["loadfile", media_path, "replace", -1, f"start={float(start):.3f}"])
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
    try:
        spawn(build_argv(config, media_path, start, sock), stdin=subprocess.DEVNULL,
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    except OSError as e:
        raise SyllabusError(f"Could not start {config['player']['command']}: {e.strerror or e}", PLAYER)
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
