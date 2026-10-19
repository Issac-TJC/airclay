"""Versioned, full-state localhost messages. Uses only the standard library."""
import json
import math
import socket
import time
import uuid

VERSION = 1
PREVIEW_VERSION = 2
MAX_PACKET_BYTES = 4096  # Localhost only; bounded below the receiver's read size.
SIDES = ("Left", "Right")
FINGERTIPS = {"thumb": 4, "index": 8, "middle": 12, "ring": 16, "pinky": 20}
FINGER_LABELS = dict(zip(FINGERTIPS, "TIMRP"))
HAND_COLORS = {"Left": (.2, .6, 1., 1.), "Right": (1., .5, .15, 1.)}
IMAGE_SPACE = "mirrored_image_normalized"
LOCAL_HAND_SPACE = "mediapipe_hand_centered_m"
HAND_PROFILE = "hand_preview"


def valid_landmarks(points, dimensions, bound):
    return (isinstance(points, (list, tuple)) and len(points) == 21
            and all(isinstance(p, (list, tuple)) and len(p) == dimensions
                    and all(finite_number(v) and abs(v) <= bound for v in p) for p in points))


def skeleton_hands(frame):
    hands = {}
    for side in SIDES:
        source = frame.get("hands", {}).get(side, {})
        image = source.get("image", [])
        xy = [p[:2] for p in image] if isinstance(image, list) and all(isinstance(p, list) for p in image) else []
        world = source.get("world", [])
        valid = bool(source.get("valid", False)) and valid_landmarks(xy, 2, 4) and valid_landmarks(world, 3, 2)
        hands[side] = {"valid": valid,
                       "image": [[round(float(v), 6) for v in p] for p in xy] if valid else None,
                       "local_world": [[round(float(v), 6) for v in p] for p in world] if valid else None}
    return hands


def finite_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def valid_xy(point):
    return (isinstance(point, (list, tuple)) and len(point) == 2
            and all(finite_number(v) and 0 <= v <= 1 for v in point))


def image_to_region(point, width, height):
    """Mirrored image: x right, y down. Blender WINDOW region: x right, y up.

    Input has already been mirrored before detection; never mirror x again.
    Hand IDs denote anatomical hands, independent of dominant-hand role.
    """
    if not valid_xy(point) or width <= 0 or height <= 0:
        raise ValueError("Invalid image point or viewport dimensions")
    return point[0] * width, (1 - point[1]) * height


def _validate_preview(packet):
    expected = {"version", "profile", "session", "seq", "timestamp_ms", "sent_ms",
                "dominant", "coordinate_space", "depth_available", "hands"}
    if packet.get("profile") == HAND_PROFILE:
        expected.add("local_world_space")
    if (set(packet) != expected or packet["profile"] not in ("hover2d", HAND_PROFILE)
            or packet["coordinate_space"] != IMAGE_SPACE or packet["depth_available"] is not False):
        raise ValueError("Unsupported v2 preview profile")
    if not finite_number(packet["sent_ms"]):
        raise ValueError("Invalid send time")
    if not isinstance(packet["hands"], dict) or set(packet["hands"]) != set(SIDES):
        raise ValueError("Expected Left and Right hand slots")
    if packet["profile"] == HAND_PROFILE:
        if packet["local_world_space"] != LOCAL_HAND_SPACE:
            raise ValueError("Unsupported local hand coordinates")
        for hand in packet["hands"].values():
            if not isinstance(hand, dict) or set(hand) != {"valid", "image", "local_world"} or type(hand["valid"]) is not bool:
                raise ValueError("Invalid skeleton hand")
            if hand["valid"]:
                if not valid_landmarks(hand["image"], 2, 4) or not valid_landmarks(hand["local_world"], 3, 2):
                    raise ValueError("Expected finite 21-joint skeleton")
            elif hand["image"] is not None or hand["local_world"] is not None:
                raise ValueError("Invalid hands must clear skeleton coordinates")
        return
    for hand in packet["hands"].values():
        if not isinstance(hand, dict) or set(hand) != {"valid", "fingertips"} or type(hand["valid"]) is not bool:
            raise ValueError("Invalid preview hand")
        tips = hand["fingertips"]
        if not isinstance(tips, list) or len(tips) > 5:
            raise ValueError("Invalid fingertip list")
        seen = set()
        for tip in tips:
            if not isinstance(tip, dict) or set(tip) != {"finger_id", "xy", "valid", "xyz", "depth_confidence"}:
                raise ValueError("Invalid fingertip fields")
            finger = tip["finger_id"]
            if not isinstance(finger, str) or finger not in FINGERTIPS or finger in seen:
                raise ValueError("Unknown or duplicate finger ID")
            seen.add(finger)
            if type(tip["valid"]) is not bool or (tip["valid"] and not hand["valid"]):
                raise ValueError("Invalid fingertip validity")
            if not valid_xy(tip["xy"]) and not (tip["xy"] is None and not tip["valid"]):
                raise ValueError("Invalid fingertip coordinates")
            if tip["xyz"] is not None or tip["depth_confidence"] is not None:
                raise ValueError("Depth is unavailable in hover2d")


def preview_hands(frame):
    """Produce a full ten-slot snapshot; absent/out-of-frame tips are invalid.

    MediaPipe world coordinates and handedness scores are deliberately excluded:
    neither represents camera-space depth or per-joint tracking confidence.
    """
    hands = {}
    for side in SIDES:
        source = frame.get("hands", {}).get(side, {})
        valid = bool(source.get("valid", False))
        landmarks = source.get("image") or []
        tips = []
        for finger, index in FINGERTIPS.items():
            point = landmarks[index][:2] if index < len(landmarks) else None
            usable = valid and valid_xy(point)
            tips.append({"finger_id": finger, "xy": [round(float(v), 6) for v in point] if usable else None,
                         "valid": usable, "xyz": None, "depth_confidence": None})
        hands[side] = {"valid": valid, "fingertips": tips}
    return hands


def build_packet(frame, state, cfg, session, seq, sent_ms=None):
    version = cfg.get("interaction_version", VERSION)
    packet = {"version": version, "session": session, "seq": seq,
              "timestamp_ms": frame["timestamp_ms"],
              "sent_ms": time.monotonic() * 1000 if sent_ms is None else sent_ms,
              "dominant": cfg["dominant"]}
    if version == PREVIEW_VERSION:
        profile = cfg.get("preview_profile", "hover2d")
        packet.update(profile=profile, coordinate_space=IMAGE_SPACE, depth_available=False)
        if profile == HAND_PROFILE:
            packet.update(local_world_space=LOCAL_HAND_SPACE, hands=skeleton_hands(frame))
        else:
            packet.update(hands=preview_hands(frame))
    elif version == VERSION:
        hands = {}
        for side in SIDES:
            h = frame.get("hands", {}).get(side, {})
            pointer = h.get("image", [[0.5, 0.5, 0]] * 21)[8][:2]
            hands[side] = {"valid": h.get("valid", False), "pointer": [max(0., min(1., float(v))) for v in pointer]}
        packet.update(hands=hands, **{k: state[k] for k in ("mode", "operation_id", "paused", "outcome")})
    return validate(packet)


def encode_packet(packet):
    raw = json.dumps(validate(packet), allow_nan=False, separators=(",", ":")).encode()
    if len(raw) > MAX_PACKET_BYTES:
        raise ValueError("Message exceeds localhost payload limit")
    return raw


def validate(packet):
    if not isinstance(packet, dict) or type(packet.get("version")) is not int or packet["version"] not in (VERSION, PREVIEW_VERSION):
        raise ValueError("Unsupported message")
    if not isinstance(packet.get("session"), str) or len(packet["session"]) > 100:
        raise ValueError("Invalid session")
    for name in (("seq", "operation_id") if packet["version"] == VERSION else ("seq",)):
        if type(packet.get(name)) is not int or packet[name] < 0:
            raise ValueError("Invalid sequence/operation")
    if not finite_number(packet.get("timestamp_ms")):
        raise ValueError("Invalid timestamp")
    if packet.get("dominant") not in ("Left", "Right"):
        raise ValueError("Invalid handedness")
    if packet["version"] == PREVIEW_VERSION:
        _validate_preview(packet)
        return packet
    if packet.get("mode") not in ("idle", "sculpt", "orbit", "resize"):
        raise ValueError("Unsupported mode")
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
        self.version = None
        self.profile = None

    def accept(self, packet):
        validate(packet)
        session = packet["session"]
        if session in self.retired:
            return False
        if session == self.session and (packet["version"] != self.version or packet.get("profile") != self.profile):
            return False  # Changing protocol requires a fresh session.
        if session != self.session:
            if self.session is not None:
                self.retired.add(self.session)
            self.session, self.seq = session, -1
            self.version = packet["version"]
            self.profile = packet.get("profile")
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
        packet = build_packet(frame, state, self.cfg, self.session, self.seq)
        raw = encode_packet(packet)
        self.seq += 1
        self.sock.sendto(raw, self.address)
        return packet

    def close(self):
        self.sock.close()
