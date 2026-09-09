"""Versioned, full-state localhost messages. Uses only the standard library."""
import json
import math
import socket
import time
import uuid

VERSION = 1


def validate(packet):
    if packet.get("version") != VERSION or packet.get("mode") not in ("idle", "sculpt", "orbit", "resize"):
        raise ValueError("Unsupported message")
    if not isinstance(packet.get("session"), str) or len(packet["session"]) > 100:
        raise ValueError("Invalid session")
    for name in ("seq", "operation_id"):
        if type(packet.get(name)) is not int or packet[name] < 0:
            raise ValueError("Invalid sequence/operation")
    if not isinstance(packet.get("timestamp_ms"), (float, int)) or not math.isfinite(packet["timestamp_ms"]):
        raise ValueError("Invalid timestamp")
    if packet.get("dominant") not in ("Left", "Right"):
        raise ValueError("Invalid handedness")
    if packet.get("outcome") not in (None, "commit", "cancel"):
        raise ValueError("Invalid outcome")
    if type(packet.get("paused")) is not bool:
        raise ValueError("Invalid pause flag")
    for side in ("Left", "Right"):
        hand = packet["hands"][side]
        if type(hand.get("valid")) is not bool:
            raise ValueError("Invalid validity")
        point = hand["pointer"]
        if len(point) != 2 or any(not isinstance(v, (float, int)) or not math.isfinite(v) or not 0 <= v <= 1 for v in point):
            raise ValueError("Invalid pointer")
    return packet


class PacketGate:
    def __init__(self):
        self.session = None
        self.retired = set()
        self.seq = -1

    def accept(self, packet):
        validate(packet)
        session = packet["session"]
        if session in self.retired:
            return False
        if session != self.session:
            if self.session is not None:
                self.retired.add(self.session)
            self.session, self.seq = session, -1
        if packet["seq"] <= self.seq:
            return False
        self.seq = packet["seq"]
        return True


class Sender:
    def __init__(self, cfg):
        self.cfg = cfg
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.setblocking(False)
        self.address = (cfg["host"], cfg["port"])
        self.session = uuid.uuid4().hex
        self.seq = 0

    def controls(self):
        result = None
        while True:
            try:
                data, addr = self.sock.recvfrom(4096)
                msg = json.loads(data)
                if addr == self.address and msg.get("type") == "settings" and msg.get("dominant") in ("Left", "Right"):
                    result = msg["dominant"]
            except BlockingIOError:
                return result
            except (ValueError, OSError):
                return result

    def send(self, frame, state):
        hands = {}
        for side in ("Left", "Right"):
            h = frame.get("hands", {}).get(side, {})
            pointer = h.get("image", [[0.5, 0.5, 0]] * 21)[8][:2]
            hands[side] = {"valid": h.get("valid", False), "pointer": [max(0., min(1., float(v))) for v in pointer]}
        packet = {"version": VERSION, "session": self.session, "seq": self.seq,
                  "timestamp_ms": frame["timestamp_ms"], "sent_ms": time.monotonic() * 1000,
                  "dominant": self.cfg["dominant"], "hands": hands,
                  **{k: state[k] for k in ("mode", "operation_id", "paused", "outcome")}}
        self.seq += 1
        self.sock.sendto(json.dumps(validate(packet), allow_nan=False).encode(), self.address)
        return packet

    def close(self):
        self.sock.close()
