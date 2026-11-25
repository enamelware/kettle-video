# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Kettle spike (the folder dialog spike): a minimal D-Bus session-bus client, standard
library only.

The desktop portal answers a folder request with a signal sent later, to
the connection that asked. A command-line tool (gdbus, busctl) exits right
after asking, and the portal then drops the request, so the answer never
arrives. This keeps one connection open for as long as the dialog is up.

Only what the spike needs: connect, authenticate, call a method, and wait
for a signal. Little-endian only. Not part of the app.
"""

import os
import socket
import struct
import time

CALL, RETURN, ERROR, SIGNAL = 1, 2, 3, 4
_FIELDS = {1: "path", 2: "interface", 3: "member", 4: "error_name",
           5: "reply_serial", 6: "destination", 7: "sender", 8: "signature"}
_FIELD_SIGS = {1: "o", 2: "s", 3: "s", 4: "s", 5: "u", 6: "s", 7: "s", 8: "g"}
_ALIGN = {"y": 1, "b": 4, "n": 2, "q": 2, "i": 4, "u": 4, "x": 8, "t": 8, "d": 8,
          "s": 4, "o": 4, "g": 1, "v": 1, "a": 4, "(": 8, "{": 8, "h": 4}
_FIXED = {"y": "B", "b": "I", "n": "h", "q": "H", "i": "i", "u": "I", "x": "q",
          "t": "Q", "d": "d", "h": "I"}


class DBusError(Exception):
    pass


def split_types(sig):
    """'sa{sv}u' -> ['s', 'a{sv}', 'u']"""
    out, i = [], 0
    while i < len(sig):
        end = _type_end(sig, i)
        out.append(sig[i:end])
        i = end
    return out


def _type_end(sig, i):
    c = sig[i]
    if c == "a":
        return _type_end(sig, i + 1)
    if c in "({":
        close = ")" if c == "(" else "}"
        depth, j = 0, i
        while True:
            if sig[j] == c:
                depth += 1
            elif sig[j] == close:
                depth -= 1
                if depth == 0:
                    return j + 1
            j += 1
    return i + 1


class _Writer:
    def __init__(self):
        self.buf = bytearray()

    def pad(self, n):
        self.buf += b"\0" * (-len(self.buf) % n)

    def write(self, sig, value):
        c = sig[0]
        self.pad(_ALIGN[c])
        if c in _FIXED:
            self.buf += struct.pack("<" + _FIXED[c], int(value))
        elif c in "so":
            data = value.encode()
            self.buf += struct.pack("<I", len(data)) + data + b"\0"
        elif c == "g":
            data = value.encode()
            self.buf += bytes([len(data)]) + data + b"\0"
        elif c == "v":
            inner_sig, inner = value
            self.write("g", inner_sig)
            self.write(inner_sig, inner)
        elif c == "a":
            elem = sig[1:]
            self.buf += b"\0\0\0\0"
            at = len(self.buf)
            self.pad(_ALIGN[elem[0]])
            start = len(self.buf)
            items = value.items() if elem[0] == "{" else value
            for item in items:
                self.write(elem, item)
            struct.pack_into("<I", self.buf, at - 4, len(self.buf) - start)
        elif c in "({":
            for part, item in zip(split_types(sig[1:-1]), value):
                self.write(part, item)
        else:
            raise DBusError(f"type {c!r} not supported")


class _Reader:
    def __init__(self, data, pos=0):
        self.data, self.pos = data, pos

    def pad(self, n):
        self.pos += -self.pos % n

    def read(self, sig):
        c = sig[0]
        self.pad(_ALIGN[c])
        if c in _FIXED:
            fmt = "<" + _FIXED[c]
            (value,) = struct.unpack_from(fmt, self.data, self.pos)
            self.pos += struct.calcsize(fmt)
            return bool(value) if c == "b" else value
        if c in "so":
            (n,) = struct.unpack_from("<I", self.data, self.pos)
            value = self.data[self.pos + 4:self.pos + 4 + n].decode("utf-8", "replace")
            self.pos += 4 + n + 1
            return value
        if c == "g":
            n = self.data[self.pos]
            value = self.data[self.pos + 1:self.pos + 1 + n].decode()
            self.pos += 1 + n + 1
            return value
        if c == "v":
            return self.read(self.read("g"))
        if c == "a":
            elem = sig[1:]
            (n,) = struct.unpack_from("<I", self.data, self.pos)
            self.pos += 4
            self.pad(_ALIGN[elem[0]])
            end = self.pos + n
            items = []
            while self.pos < end:
                items.append(self.read(elem))
            return dict(items) if elem[0] == "{" else items
        if c in "({":
            return tuple(self.read(part) for part in split_types(sig[1:-1]))
        raise DBusError(f"type {c!r} not supported")


def _bus_path():
    address = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    for part in address.split(";"):
        kind, _, rest = part.partition(":")
        params = dict(p.split("=", 1) for p in rest.split(",") if "=" in p)
        if kind == "unix" and "path" in params:
            return params["path"]
        if kind == "unix" and "abstract" in params:
            return "\0" + params["abstract"]
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(runtime, "bus")


class SessionBus:
    def __init__(self, timeout=5):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect(_bus_path())
        self.serial = 0
        self.pending = []  # messages read while waiting for something else
        self._auth()
        self.unique_name = self.call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                     "org.freedesktop.DBus", "Hello")[0]

    def close(self):
        self.sock.close()

    def _auth(self):
        uid = str(os.getuid()).encode().hex()
        self.sock.sendall(b"\0AUTH EXTERNAL " + uid.encode() + b"\r\n")
        line = b""
        while not line.endswith(b"\r\n"):
            line += self.sock.recv(1)
        if not line.startswith(b"OK"):
            raise DBusError("the session bus refused the connection")
        self.sock.sendall(b"BEGIN\r\n")

    def _send(self, kind, fields, sig="", args=()):
        self.serial += 1
        body = _Writer()
        for part, value in zip(split_types(sig), args):
            body.write(part, value)
        if sig:
            fields = {**fields, 8: sig}
        header = _Writer()
        header.buf += struct.pack("<cBBBII", b"l", kind, 0, 1, len(body.buf), self.serial)
        header.write("a(yv)", [(code, (_FIELD_SIGS[code], value)) for code, value in fields.items()])
        header.pad(8)
        self.sock.sendall(bytes(header.buf) + bytes(body.buf))
        return self.serial

    def _recv_exact(self, n):
        data = b""
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise DBusError("the session bus closed the connection")
            data += chunk
        return data

    def _read_message(self):
        fixed = self._recv_exact(16)
        if fixed[0:1] != b"l":
            raise DBusError("big-endian messages are not supported")
        kind = fixed[1]
        body_len, serial, fields_len = struct.unpack_from("<III", fixed, 4)
        rest = self._recv_exact(fields_len + (-(16 + fields_len) % 8) + body_len)
        data = fixed + rest
        reader = _Reader(data, 12)
        fields = {_FIELDS.get(code, code): value for code, value in reader.read("a(yv)")}
        reader.pad(8)
        sig = fields.get("signature", "")
        body = [reader.read(part) for part in split_types(sig)]
        return {"type": kind, "serial": serial, "body": body, **fields}

    def call(self, dest, path, iface, member, sig="", args=(), timeout=10):
        serial = self._send(CALL, {1: path, 2: iface, 3: member, 6: dest}, sig, args)
        end = time.monotonic() + timeout
        while True:
            self.sock.settimeout(max(0.01, end - time.monotonic()))
            try:
                msg = self._read_message()
            except socket.timeout:
                raise DBusError(f"{member}: no answer within {timeout} s") from None
            if msg["type"] in (RETURN, ERROR) and msg.get("reply_serial") == serial:
                if msg["type"] == ERROR:
                    raise DBusError(f"{msg.get('error_name')}: {msg['body'][0] if msg['body'] else ''}")
                return msg["body"]
            self.pending.append(msg)

    def get_property(self, dest, path, iface, name):
        return self.call(dest, path, "org.freedesktop.DBus.Properties", "Get",
                         "ss", (iface, name))[0]

    def add_match(self, rule):
        self.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                  "AddMatch", "s", (rule,))

    def wait_signal(self, path, member, timeout, stop=None):
        """The body of the first signal `member` on `path`, or None when the
        timeout passes or stop() turns true (checked every 0.2 s)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for msg in self.pending:
                if msg["type"] == SIGNAL and msg.get("path") == path and msg.get("member") == member:
                    self.pending.remove(msg)
                    return msg["body"]
            if stop and stop():
                return None
            self.sock.settimeout(0.2)
            try:
                self.pending.append(self._read_message())
            except socket.timeout:
                continue
        return None
