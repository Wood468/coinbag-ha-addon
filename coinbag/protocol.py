"""Pokémon GO postcard-exchange protocol (Python port of the web/Android reference implementation).

Reference: https://github.com/na-ji/pokemon-go-coin-bag (PROTOCOL.md, docs/protocol.js).
Constants (UUIDs, RSA material) are the upstream project's, kept verbatim in constants.json.
"""
import hashlib
import json
import os
import secrets
import uuid as _uuid
from dataclasses import dataclass

_C = json.load(open(os.path.join(os.path.dirname(__file__), "constants.json")))
UUIDS = _C["UUIDS"]
APPLICATION_ID_SUFFIX = _C["APPLICATION_ID_SUFFIX"]
APPLICATION_ID_GATT_WIDTH = _C["APPLICATION_ID_GATT_WIDTH"]
_N = int(_C["RSA_MODULUS"], 16)
_D = int(_C["RSA_PRIVATE_EXPONENT"], 16)
_PREFIX = bytes.fromhex(_C["SHA256_DIGEST_INFO_PREFIX"])
MASK64 = (1 << 64) - 1


# ---- protobuf (varint + length-delimited only) ----
def encode_varint(value: int) -> bytes:
    value &= MASK64 if value < 0 else value
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def decode_varint(data: bytes, offset: int = 0):
    value = shift = 0
    while offset < len(data) and shift < 70:
        octet = data[offset]
        offset += 1
        value |= (octet & 0x7F) << shift
        if not octet & 0x80:
            return value, offset
        shift += 7
    raise ValueError("Invalid or truncated protobuf varint")


def _bytes_field(number: int, value: bytes) -> bytes:
    return encode_varint((number << 3) | 2) + encode_varint(len(value)) + value


def _varint_field(number: int, value: int) -> bytes:
    return encode_varint(number << 3) + encode_varint(value)


def _parse_fields(data: bytes) -> dict:
    fields, offset = {}, 0
    while offset < len(data):
        tag, offset = decode_varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if number == 0:
            raise ValueError("Protobuf field number zero")
        if wire == 0:
            value, offset = decode_varint(data, offset)
            fields[number] = (wire, value)
        elif wire == 2:
            length, offset = decode_varint(data, offset)
            end = offset + length
            if end > len(data):
                raise ValueError("Truncated protobuf length-delimited field")
            fields[number] = (wire, bytes(data[offset:end]))
            offset = end
        else:
            raise ValueError(f"Unsupported protobuf wire type {wire}")
    return fields


def _req_bytes(fields, n) -> bytes:
    f = fields.get(n)
    if not f:
        raise ValueError(f"Missing protobuf field {n}")
    if f[0] != 2:
        raise ValueError(f"Protobuf field {n} is not length-delimited")
    return f[1]


def _req_varint(fields, n) -> int:
    f = fields.get(n)
    if not f:
        raise ValueError(f"Missing protobuf field {n}")
    if f[0] != 0:
        raise ValueError(f"Protobuf field {n} is not a varint")
    return f[1]


@dataclass
class BleSend:
    data: int
    transaction_id: int
    application_id: str
    nonce: str
    server_signature: bytes


@dataclass
class BleFinalize:
    nonce: str
    application_id: str
    server_signature: bytes


def decode_ble_send(data: bytes) -> BleSend:
    outer = _parse_fields(data)
    prep = _parse_fields(_req_bytes(outer, 1))
    return BleSend(
        _req_varint(prep, 1), _req_varint(prep, 2),
        _req_bytes(prep, 3).decode("utf-8"), _req_bytes(prep, 4).decode("utf-8"),
        _req_bytes(outer, 2),
    )


def decode_ble_finalize(data: bytes) -> BleFinalize:
    outer = _parse_fields(data)
    inner = _parse_fields(_req_bytes(outer, 1))
    return BleFinalize(
        _req_bytes(inner, 1).decode("utf-8"), _req_bytes(inner, 2).decode("utf-8"),
        _req_bytes(outer, 2),
    )


def encode_share(transaction_id: int, nonce: str) -> bytes:
    return _varint_field(1, transaction_id) + _bytes_field(2, nonce.encode("utf-8"))


# ---- RSA PKCS#1 v1.5 / SHA-256 (deterministic) ----
def rsa_signature(message: bytes) -> bytes:
    digest = hashlib.sha256(message).digest()
    pad = 256 - 3 - len(_PREFIX) - len(digest)
    if pad < 8:
        raise ValueError("Digest encoding does not fit RSA modulus")
    encoded = b"\x00\x01" + b"\xff" * pad + b"\x00" + _PREFIX + digest
    return pow(int.from_bytes(encoded, "big"), _D, _N).to_bytes(256, "big")


def encode_complete(transaction_id: int, nonce: str) -> bytes:
    share = encode_share(transaction_id, nonce)
    sig = rsa_signature(share)
    return _bytes_field(1, share) + _bytes_field(2, sig) + _bytes_field(3, sig[:16])


# ---- ids, nonces, GATT values ----
def generate_application_id() -> str:
    ns = bytes.fromhex("6ba7b8109dad11d180b400c04fd430c8")
    h = bytearray(hashlib.sha1(ns + secrets.token_bytes(16)).digest())
    h[6] = (h[6] & 0x0F) | 0x50
    h[8] = (h[8] & 0x3F) | 0x80
    return str(_uuid.UUID(bytes=bytes(h[:16]))) + APPLICATION_ID_SUFFIX


def application_id_gatt_value(app_id: str) -> bytes:
    if not app_id.endswith(APPLICATION_ID_SUFFIX):
        raise ValueError(f"Application ID must end with {APPLICATION_ID_SUFFIX}")
    enc = app_id.encode("utf-8")
    if len(enc) > APPLICATION_ID_GATT_WIDTH:
        raise ValueError("Application ID exceeds the 69-byte GATT field")
    return enc.ljust(APPLICATION_ID_GATT_WIDTH, b"\x00")


def decode_player_name(value: bytes) -> str:
    if not 4 <= len(value) <= 15:
        raise ValueError("Player name must be 4..15 UTF-8 bytes")
    return value.decode("utf-8")


def initial_nonce_value(nonce: str) -> bytes:
    enc = nonce.encode("utf-8")
    if b"\x00" in enc:
        raise ValueError("Nonce contains NUL")
    return enc + b"\x00"


def final_nonce_value(nonce: str) -> bytes:
    enc = nonce.encode("utf-8")
    if b"\x00" in enc:
        raise ValueError("Nonce contains NUL")
    return enc


def nonce_from_tick(tick: int) -> str:
    tick &= MASK64
    value = 0xCBF29CE484222645
    for i in range(8):
        value ^= (tick >> (8 * i)) & 0xFF
        value = (value * 0x100000001B3) & MASK64
    return format(value, "x")


def random_nonce() -> str:
    return nonce_from_tick(secrets.randbits(64))


def validate_send(msg: BleSend, app_id: str, nonce: str):
    if msg.application_id != app_id:
        raise ValueError("Server response application ID mismatch")
    if msg.nonce != nonce:
        raise ValueError("Server response nonce mismatch")


def validate_finalize(msg: BleFinalize, app_id: str, nonce: str):
    if msg.application_id != app_id:
        raise ValueError("Finalize application ID mismatch")
    if msg.nonce != nonce:
        raise ValueError("Finalize nonce mismatch")
