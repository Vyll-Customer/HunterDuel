"""Tiny one-opponent TCP transport for Hunter Duel.

The host is authoritative. Messages are newline-delimited JSON and capped to
64 KiB so malformed peers cannot make the receive buffer grow forever.
"""

from __future__ import annotations

from collections import deque
import json
import queue
import socket
import threading
from typing import Any


PROTOCOL_VERSION = 1
DEFAULT_PORT = 50505
MAX_MESSAGE = 65_536


def local_ip() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


class NetworkPeer:
    def __init__(self, role: str, address: str = "127.0.0.1", port: int = DEFAULT_PORT):
        if role not in ("host", "client"):
            raise ValueError("role must be host or client")
        self.role = role
        self.address = address
        self.port = int(port)
        self.connected = threading.Event()
        self.stopped = threading.Event()
        self.error = ""
        self._outgoing: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=180)
        self._incoming: deque[dict[str, Any]] = deque(maxlen=360)
        self._lock = threading.Lock()
        self._socket: socket.socket | None = None
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name=f"hunter-net-{self.role}", daemon=True)
        self._thread.start()

    def send(self, payload: dict[str, Any]) -> None:
        if self.stopped.is_set():
            return
        try:
            self._outgoing.put_nowait(payload)
        except queue.Full:
            try:
                self._outgoing.get_nowait()
                self._outgoing.put_nowait(payload)
            except queue.Empty:
                pass

    def drain(self) -> list[dict[str, Any]]:
        with self._lock:
            messages = list(self._incoming)
            self._incoming.clear()
        return messages

    def close(self) -> None:
        self.stopped.set()
        for sock in (self._socket, self._server):
            if sock:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    sock.close()
                except OSError:
                    pass

    def _run(self) -> None:
        try:
            if self.role == "host":
                server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._server = server
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind(("0.0.0.0", self.port))
                server.listen(1)
                server.settimeout(0.25)
                while not self.stopped.is_set():
                    try:
                        sock, _ = server.accept()
                        break
                    except socket.timeout:
                        continue
                else:
                    return
            else:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5.0)
                sock.connect((self.address, self.port))

            self._socket = sock
            sock.settimeout(0.02)
            self.connected.set()
            self.send({"type": "hello", "protocol": PROTOCOL_VERSION, "role": self.role})
            buffer = bytearray()
            while not self.stopped.is_set():
                self._flush(sock)
                try:
                    chunk = sock.recv(8192)
                    if not chunk:
                        raise ConnectionError("The other player disconnected.")
                    buffer.extend(chunk)
                    if len(buffer) > MAX_MESSAGE * 2:
                        raise ValueError("Network message was too large.")
                    while b"\n" in buffer:
                        raw, _, remainder = buffer.partition(b"\n")
                        buffer = bytearray(remainder)
                        if not raw or len(raw) > MAX_MESSAGE:
                            continue
                        message = json.loads(raw.decode("utf-8"))
                        if isinstance(message, dict):
                            with self._lock:
                                self._incoming.append(message)
                except socket.timeout:
                    continue
        except (OSError, ConnectionError, ValueError, json.JSONDecodeError) as exc:
            if not self.stopped.is_set():
                self.error = str(exc)
        finally:
            self.stopped.set()
            self.connected.clear()

    def _flush(self, sock: socket.socket) -> None:
        for _ in range(24):
            try:
                message = self._outgoing.get_nowait()
            except queue.Empty:
                return
            encoded = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
            if len(encoded) <= MAX_MESSAGE:
                sock.sendall(encoded)

