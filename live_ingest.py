"""Reading this machine's own connection table, to see whether OBS is sending.

Why this exists: the platform's answer to "is the broadcast live" costs a request
and can lag behind reality by seconds. OBS opening a socket to the ingest endpoint
is immediate and free, and it is the moment the user is actually waiting for. So it
is watched directly.

The table is read from the operating system, not by connecting anywhere: probing a
port would only prove the *server* is reachable, which is true whether or not
anyone is streaming, and would be a lie dressed as a signal. Reading the table has
no dependencies — the Windows path is ``ctypes``, which is standard library.

Every path degrades to ``False``, which means "I cannot see OBS". That leaves the
platform poll as the source of truth. It never means "the stream is not live".
"""

from __future__ import annotations

import ctypes
import logging
import socket
import sys
from functools import lru_cache

LOGGER = logging.getLogger(__name__)

DEFAULT_RTMP_PORT = 1935
# The states in the OS table that mean "this socket is up". Only established
# connections count: a socket still connecting has not carried a frame yet.
_ESTABLISHED = 5
_TABLE_OWNER_PID_ALL = 5
_AF_INET = 2


def ingest_endpoint(rtmp_url: str) -> tuple[str, int]:
    """Return the ``(host, port)`` OBS will connect to for this RTMP URL.

    OBS points at the ingest endpoint it was given, so this reads back exactly what
    the user was told to paste. Anything unparseable yields no endpoint, which
    disables this detector instead of producing a wrong answer.
    """

    text = (rtmp_url or "").strip()
    if not text:
        return "", 0
    without_scheme = text.split("://", 1)[-1]
    authority = without_scheme.split("/", 1)[0].split("?", 1)[0]
    if not authority:
        return "", 0
    if authority.startswith("["):  # IPv6 literal, [::1]:1935
        host, _, rest = authority[1:].partition("]")
        port_text = rest.lstrip(":")
    elif ":" in authority:
        host, _, port_text = authority.rpartition(":")
    else:
        host, port_text = authority, ""
    try:
        port = int(port_text) if port_text else DEFAULT_RTMP_PORT
    except ValueError:
        port = DEFAULT_RTMP_PORT
    return host.strip(), port if 0 < port < 65536 else DEFAULT_RTMP_PORT


@lru_cache(maxsize=32)
def _resolve(host: str) -> frozenset[str]:
    """Resolve a host once; the ingest addresses do not change mid-stream."""

    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET)
    except (socket.gaierror, OSError):
        LOGGER.debug("No se pudo resolver %s para vigilar la ingesta", host)
        return frozenset()
    return frozenset(info[4][0] for info in infos if info[4])


def _ipv4_to_int(address: str) -> int:
    """Return the packed integer form the Windows table uses (little-endian)."""

    return int.from_bytes(socket.inet_aton(address), "little")


class _TcpRow(ctypes.Structure):
    _fields_ = [
        ("state", ctypes.c_ulong),
        ("local_addr", ctypes.c_ulong),
        ("local_port", ctypes.c_ulong),
        ("remote_addr", ctypes.c_ulong),
        ("remote_port", ctypes.c_ulong),
        ("pid", ctypes.c_ulong),
    ]


class _TcpTable(ctypes.Structure):
    # One row inline, not an array of them: ctypes aligns an array field to the
    # alignment of its element's *pointer*, which would pad this header to 8 bytes
    # and put the first row four bytes early — reading the row count as if it were
    # a socket state. The rows are walked from the address of this field instead.
    _fields_ = [("count", ctypes.c_ulong), ("first", _TcpRow)]


def _windows_remote_addresses() -> set[tuple[int, int]]:
    """Return every established remote ``(address, port)`` on this machine."""

    size = ctypes.c_ulong(0)
    iphlpapi = ctypes.windll.iphlpapi  # type: ignore[attr-defined]
    if iphlpapi.GetExtendedTcpTable(
        None, ctypes.byref(size), False, _AF_INET, _TABLE_OWNER_PID_ALL, 0
    ) not in (0, 122):
        return set()

    buffer = ctypes.create_string_buffer(size.value or 1)
    if iphlpapi.GetExtendedTcpTable(
        buffer, ctypes.byref(size), False, _AF_INET, _TABLE_OWNER_PID_ALL, 0
    ) != 0:
        return set()

    table = ctypes.cast(buffer, ctypes.POINTER(_TcpTable)).contents
    count = table.count
    if not count:
        return set()
    # The declared struct holds a single row, so the real rows are walked from the
    # address that row starts at: the table is a header followed by a variable
    # length array, which is what this API means by a table.
    first_row = ctypes.addressof(table) + _TcpTable.first.offset
    rows = ctypes.cast(first_row, ctypes.POINTER(_TcpRow * count)).contents
    return {
        (row.remote_addr, socket.ntohs(row.remote_port & 0xFFFF))
        for row in rows
        if row.state == _ESTABLISHED
    }


def _proc_net_addresses() -> set[tuple[int, int]]:
    """Read ``/proc/net/tcp`` on Linux, where the table is a plain file."""

    import struct

    addresses: set[tuple[int, int]] = set()
    try:
        with open("/proc/net/tcp", encoding="ascii", errors="replace") as handle:
            next(handle, None)  # header
            for line in handle:
                parts = line.split()
                if len(parts) < 4 or parts[3] != "01":  # 01 = ESTABLISHED
                    continue
                remote_hex = parts[2].split(":")[0]
                if len(remote_hex) != 8:
                    continue
                packed = struct.pack("<L", int(remote_hex, 16))
                port = int(parts[2].split(":")[1], 16)
                addresses.add((int.from_bytes(packed, "big"), port))
    except (OSError, ValueError, StopIteration):
        return set()
    return addresses


def _psutil_addresses() -> set[tuple[int, int]]:
    """Used only on platforms without either reader, and only if it is installed."""

    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        return set()
    addresses: set[tuple[int, int]] = set()
    try:
        for connection in psutil.net_connections(kind="tcp"):
            if connection.raddr and connection.status == psutil.CONN_ESTABLISHED:
                addresses.add(
                    (_ipv4_to_int(connection.raddr.ip), int(connection.raddr.port))
                )
    except Exception:  # pragma: no cover - permissions vary by platform
        return set()
    return addresses


def established_remote_addresses() -> set[tuple[int, int]]:
    """Return established remote endpoints, using whichever reader this OS allows."""

    if sys.platform == "win32":
        try:
            return _windows_remote_addresses()
        except Exception:  # pragma: no cover - a probe must never raise
            LOGGER.debug("No se pudo leer la tabla TCP de Windows", exc_info=True)
            return set()
    if sys.platform.startswith("linux"):
        return _proc_net_addresses()
    return _psutil_addresses()


def ingest_connected(rtmp_url: str) -> bool:
    """Return whether this machine has an established connection to the ingest host.

    ``True`` means OBS has a socket open to the endpoint the credentials were issued
    for — it is sending. ``False`` means it could not be seen, which is not proof
    that nothing is sending, so callers must combine this with the platform's
    answer rather than treating it as "offline".
    """

    host, port = ingest_endpoint(rtmp_url)
    if not host or not port:
        return False

    resolved = _resolve(host)
    if not resolved:
        return False
    wanted = {_ipv4_to_int(address) for address in resolved}

    for address, remote_port in established_remote_addresses():
        if remote_port == port and address in wanted:
            return True
    return False
