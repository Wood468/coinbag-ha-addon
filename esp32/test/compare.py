"""Compare host_test output with the Python add-on's protocol.py (run from repo root after fetch_constants)."""
import subprocess, sys, uuid, hashlib
sys.path.insert(0, "coinbag")
import protocol as P
got = dict(l.split("=", 1) for l in subprocess.check_output([sys.argv[1]], text=True).split())
rnd = bytes((i * 7 + 1) & 255 for i in range(16))
ns = bytes.fromhex("6ba7b8109dad11d180b400c04fd430c8")
h = bytearray(hashlib.sha1(ns + rnd).digest()); h[6] = (h[6] & 15) | 0x50; h[8] = (h[8] & 0x3F) | 0x80
appid = str(uuid.UUID(bytes=bytes(h[:16]))) + P.APPLICATION_ID_SUFFIX
want = {"complete": P.encode_complete(12345, "abcdef0123456789").hex(), "nonce": P.nonce_from_tick(0x0123456789abcdef),
        "appid": appid, "gatt": P.application_id_gatt_value(appid).hex()}
bad = [k for k in want if want[k] != got.get(k)]
print("MISMATCH:" if bad else "all protocol outputs match", bad)
sys.exit(1 if bad else 0)
