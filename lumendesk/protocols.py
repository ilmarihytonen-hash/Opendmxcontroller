from __future__ import annotations

import struct
import uuid

CHANNELS_PER_UNIVERSE = 512


def _validate_universe(universe: int, data: bytes, maximum: int) -> None:
    if not 1 <= universe <= maximum:
        raise ValueError(f"Universe must be between 1 and {maximum}.")
    if len(data) != CHANNELS_PER_UNIVERSE:
        raise ValueError("A DMX universe must contain exactly 512 channel values.")


def make_artnet_packet(universe: int, data: bytes, sequence: int = 1) -> bytes:
    _validate_universe(universe, data, 32768)
    payload = data if len(data) % 2 == 0 else data + b"\x00"
    return (
        b"Art-Net\x00"
        + struct.pack("<H", 0x5000)
        + struct.pack(">H", 14)
        + bytes((sequence % 256, 0))
        + struct.pack("<H", universe - 1)
        + struct.pack(">H", len(payload))
        + payload
    )


def _pdu(data: bytes) -> bytes:
    return struct.pack(">H", 0x7000 | (len(data) + 2)) + data


def make_sacn_packet(
    universe: int,
    data: bytes,
    sequence: int = 1,
    source_name: str = "LumenDesk",
    cid: bytes | None = None,
) -> bytes:
    _validate_universe(universe, data, 63999)
    if cid is None:
        cid = uuid.uuid4().bytes
    if len(cid) != 16:
        raise ValueError("sACN CID must be exactly 16 bytes.")
    name = source_name.encode("utf-8")[:63].ljust(64, b"\x00")

    dmp = _pdu(
        bytes((2, 0xA1))
        + struct.pack(">HHH", 0, 1, 513)
        + b"\x00"
        + data
    )
    framing = _pdu(
        struct.pack(">I", 2)
        + name
        + bytes((100,))
        + struct.pack(">H", 0)
        + bytes((sequence % 256, 0))
        + struct.pack(">H", universe)
        + dmp
    )
    root = _pdu(struct.pack(">I", 4) + cid + framing)
    return struct.pack(">HH", 0x0010, 0) + b"ASC-E1.17\x00\x00\x00" + root


def sacn_multicast_address(universe: int) -> str:
    if not 1 <= universe <= 63999:
        raise ValueError("sACN universe must be between 1 and 63999.")
    return f"239.255.{universe >> 8}.{universe & 0xFF}"
