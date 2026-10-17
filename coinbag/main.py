"""Coin Bag for Home Assistant: scans for Pokémon GO's Nintendo Switch pairing advertisement,
pairs and receives postcards automatically, and reports to HA sensors."""
import asyncio
import json
import logging
import os
import time
import urllib.request

from bleak import BleakClient, BleakScanner

import protocol as P
from pairing_agent import BlueZPairingAgent, bluez_device_path

log = logging.getLogger("coinbag")
U = P.UUIDS
ADV = U["advertisementService"].lower()
STATE_FILE = os.environ.get("COINBAG_STATE", "/data/state.json")
SUCCESS_DELAY, FAILURE_DELAY, GATT_TIMEOUT, INDICATION_TIMEOUT, SETTLE = 60.0, 3.0, 10.0, 15.0, 0.075
NOTIFY_MODE = os.environ.get("NOTIFY_MODE", "auto").strip().lower()
BACKOFF = (3.0, 10.0, 30.0, 60.0)  # seconds to wait after the 1st, 2nd, 3rd, 4th+ failure in a row; stops a pairing-prompt storm on the phone


# ---------- persistence ----------
def load_state() -> dict:
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {}


def save_state(st: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    json.dump(st, open(STATE_FILE, "w"))


# ---------- Home Assistant reporting (Supervisor proxy) ----------
def ha_set(entity: str, state, attrs: dict):
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return
    req = urllib.request.Request(
        f"http://supervisor/core/api/states/{entity}",
        data=json.dumps({"state": state, "attributes": attrs}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except Exception as e:  # reporting must never break the loop
        log.debug("HA report failed: %s", e)


def report(st: dict, status: str, detail: str = ""):
    ha_set("sensor.coinbag_status", status, {"friendly_name": "Coin Bag status", "detail": detail, "icon": "mdi:bluetooth-connect"})
    ha_set("sensor.coinbag_postcards", st.get("postcards", 0), {
        "friendly_name": "Coin Bag postcards received", "icon": "mdi:postage-stamp", "state_class": "total_increasing",
        "last_player": st.get("last_player"), "last_at": st.get("last_at"),
        "paired_with": st.get("paired", [])})


# ---------- BLE ----------
def pick_adapter() -> str:
    """ADAPTER option: 'auto' uses the highest-numbered adapter (a newly plugged USB dongle becomes hci1), else the named one."""
    want = os.environ.get("ADAPTER", "auto").strip()
    if want and want != "auto":
        return want
    try:
        hci = sorted((d for d in os.listdir("/sys/class/bluetooth") if d.startswith("hci") and ":" not in d), key=lambda d: int(d[3:]))
        return hci[-1] if hci else "hci0"
    except Exception:
        return "hci0"


async def wait_for_phone(st):
    """Scan without a BlueZ filter (more reliable) and match the Pokémon GO service ourselves.
    Every 15 s the sensor shows how many BLE devices were heard, so we can tell whether scanning works at all."""
    found, ev, seen = [], asyncio.Event(), {}

    def cb(device, adv):
        seen[device.address] = (adv.local_name or device.name or "", adv.rssi)
        if ADV in [u.lower() for u in (adv.service_uuids or [])] and not found:
            found.append(device)
            ev.set()

    adapter = pick_adapter()
    log.info("scanning with adapter %s", adapter)
    async with BleakScanner(cb, adapter=adapter):
        while not ev.is_set():
            try:
                await asyncio.wait_for(ev.wait(), 15)
            except asyncio.TimeoutError:
                names = sorted({n for n, _ in seen.values() if n})[:10]
                log.info("scanning: %d BLE devices heard in the last 15 s (%s)", len(seen), ", ".join(names))
                ha_set("sensor.coinbag_status", "scanning", {"friendly_name": "Coin Bag status", "icon": "mdi:bluetooth-connect",
                       "ble_devices_heard": len(seen), "named_devices": names})
                seen.clear()
    return found[0]


async def read(client, uuid):
    return bytes(await asyncio.wait_for(client.read_gatt_char(uuid), GATT_TIMEOUT))


async def write(client, uuid, value, response):
    await asyncio.wait_for(client.write_gatt_char(uuid, value, response=response), GATT_TIMEOUT)


async def start_indications(client, uuid, callback):
    """Subscribe using Bleak's default method or BlueZ StartNotify for compatibility testing."""
    if NOTIFY_MODE == "start":
        log.info("subscribing to %s using BlueZ StartNotify", uuid)
        await asyncio.wait_for(
            client.start_notify(uuid, callback, bluez={"use_start_notify": True}),
            GATT_TIMEOUT,
        )
    else:
        log.info("subscribing to %s using Bleak default notification method", uuid)
        await asyncio.wait_for(client.start_notify(uuid, callback), GATT_TIMEOUT)


async def exchange(client, app_id, nonce):
    # iOS GO may tear down its GATT table immediately after the finalize indication.
    # Resolve this characteristic before the exchange and reuse the object for the final write.
    final_nonce_char = client.services.get_characteristic(U["writeFinalNonce"])
    if final_nonce_char is None:
        raise RuntimeError("Final nonce characteristic was not discovered")

    # DATA is used for the first indication and may also carry finalize on Android.
    # Keep DATA subscribed throughout; iOS finalize arrives on STAGE.
    q: asyncio.Queue = asyncio.Queue()

    def on_indication(char, data):
        uuid = str(getattr(char, "uuid", char)).lower()
        log.debug("indication received on %s (%d bytes)", uuid, len(data))
        q.put_nowait((uuid, bytes(data)))

    log.info("exchange step: write application ID")
    await write(client, U["writeApplicationId"], P.application_id_gatt_value(app_id), True)
    log.info("exchange step: write initial nonce")
    await write(client, U["writeInitialNonce"], P.initial_nonce_value(nonce), False)
    log.info("exchange step: subscribe DATA indications")
    await start_indications(client, U["indicateData"], on_indication)

    log.info("exchange step: waiting for first DATA indication")
    _, first = await asyncio.wait_for(q.get(), INDICATION_TIMEOUT)
    log.info("first indication: %d bytes", len(first))
    if len(first) < 303:
        raise RuntimeError(f"First indication is only {len(first)} bytes; the negotiated ATT MTU may be insufficient")

    log.info("exchange step: decode and validate first indication")
    send = P.decode_ble_send(first)
    P.validate_send(send, app_id, nonce)
    complete = P.encode_complete(send.transaction_id, send.nonce)
    log.info("first indication validated; completion payload is %d bytes", len(complete))

    log.info("exchange step: subscribe STAGE indications")
    await start_indications(client, U["indicateStage"], on_indication)
    log.info("exchange step: write RSA completion")
    await write(client, U["writeComplete"], complete, False)
    log.info("completion written; waiting for finalize indication")

    try:
        src, final = await asyncio.wait_for(q.get(), INDICATION_TIMEOUT)
    except asyncio.TimeoutError:
        log.warning("Finalize indication timed out. Postcard likely sent, but finalization was not confirmed.")
        return False

    log.info("finalize indication on %s (%d bytes)", "STAGE" if src == U["indicateStage"].lower() else "DATA", len(final))
    log.info("exchange step: validate finalize indication")
    P.validate_finalize(P.decode_ble_finalize(final), app_id, nonce)

    # Upstream iOS implementation tolerates this write failing when GO closes GATT
    # immediately after finalize. Validate the server finalize first, then attempt the
    # final nonce write against the pre-resolved characteristic without rediscovery.
    try:
        log.info("exchange step: write final nonce")
        await asyncio.wait_for(client.write_gatt_char(final_nonce_char, P.final_nonce_value(nonce), response=True), GATT_TIMEOUT)
        log.info("final nonce write acknowledged")
    except Exception as e:
        log.warning("final nonce write failed after valid finalize (GO may have closed GATT): %s", e)
    return True


async def handle(device, st, pairing_agent):
    log.info("connecting to %s (name=%r, rssi=%s) with notify_mode=%s",
             device.address, device.name, getattr(device, "rssi", "?"), NOTIFY_MODE)

    def disconnected(client):
        log.warning("BLE disconnected from %s", device.address)

    device_path = bluez_device_path(device, pick_adapter())
    pairing_agent.set_target_device(device_path)
    log.info("armed scoped Bluetooth pairing agent for %s", device_path)
    try:
        async with BleakClient(device, timeout=GATT_TIMEOUT, pair=True, disconnected_callback=disconnected) as client:
            log.info("connected to %s, MTU %s", device.address, getattr(client, "mtu_size", "?"))
            log.debug("GATT service discovery completed; %d services available",
                      len(client.services.services))
            await asyncio.sleep(SETTLE)
            if client.services.get_characteristic(U["readProtocol"]) is None:
                log.error(
                    "GO protocol characteristic %s is missing; clearing only this phone's "
                    "BlueZ GATT cache (%s) before retrying",
                    U["readProtocol"], device.address,
                )
                await forget(device.address)
                raise RuntimeError("GO protocol characteristic missing; cleared BlueZ cache and will retry")
            proto = await read(client, U["readProtocol"])
            if proto != b"\x01":
                raise RuntimeError(f"Unsupported protocol value {list(proto)}")
            name = P.decode_player_name(await read(client, U["readName"]))
            mode = await read(client, U["readMode"])
            if len(mode) != 1:
                raise RuntimeError("Invalid mode characteristic")
            app_id = st.get("application_id")
            if not app_id:
                app_id = st["application_id"] = P.generate_application_id()
                save_state(st)
            nonce = P.random_nonce()
            if mode[0] == 0x00:
                report(st, "pairing", name)
                await asyncio.sleep(0.25)
                await write(client, U["writeApplicationId"], P.application_id_gatt_value(app_id), True)
                st.setdefault("paired", [])
                if name not in st["paired"]:
                    st["paired"].append(name)
                save_state(st)
                log.info("PAIRED with %s", name)
                return "paired", name
            if mode[0] == 0x01:
                report(st, "exchanging", name)
                confirmed = await exchange(client, app_id, nonce)
                if not confirmed:
                    log.warning("Exchange ended without a validated finalize; postcard count unchanged")
                    return "unconfirmed", name
                st["postcards"] = st.get("postcards", 0) + 1
                st["last_player"], st["last_at"] = name, time.strftime("%Y-%m-%dT%H:%M:%S%z")
                save_state(st)
                log.info("POSTCARD received from %s (total %d)", name, st["postcards"])
                return "received", name
            raise RuntimeError(f"Unsupported mode 0x{mode[0]:02x}")

    finally:
        pairing_agent.clear_target_device()

async def bluez_diag(st):
    """Log what BlueZ itself reports, so a deaf or missing adapter is obvious."""
    out = {}
    for name, args in (("show", ["show"]), ("devices", ["devices"])):
        try:
            p = await asyncio.create_subprocess_exec("bluetoothctl", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            raw, _ = await asyncio.wait_for(p.communicate(), 10)
            out[name] = raw.decode(errors="replace").strip()
        except Exception as e:
            out[name] = f"unavailable: {e}"
    log.info("bluetoothctl show:\n%s", out["show"])
    log.info("bluetoothctl devices (BlueZ cache):\n%s", out["devices"] or "(none)")
    try:  # a 12 s active scan straight through BlueZ, independent of bleak
        p = await asyncio.create_subprocess_exec("bluetoothctl", "--timeout", "12", "scan", "on", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        raw, _ = await asyncio.wait_for(p.communicate(), 25)
        text = raw.decode(errors="replace")
        found = sorted({l.split("] ")[-1].strip() for l in text.splitlines() if "NEW" in l and "Device" in l})
        log.info("bluetoothctl 12 s active scan: %d new devices\n%s", len(found), "\n".join(found[:20]) or text[-600:])
    except Exception as e:
        log.info("bluetoothctl scan failed: %s", e)
    keep = [l.strip() for l in out["show"].splitlines() if any(k in l for k in ("Controller", "Powered", "Discovering", "Roles"))]
    ha_set("sensor.coinbag_status", "starting", {"friendly_name": "Coin Bag status", "bluez": keep, "bluez_cached_devices": len([l for l in out["devices"].splitlines() if l.startswith("Device")])})


async def forget(address):
    """Drop BlueZ's cached copy of the phone (stale GATT database, old keys) so the next connection starts clean."""
    try:
        p = await asyncio.create_subprocess_exec("bluetoothctl", "remove", address, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(p.communicate(), 10)
        log.info("cleared BlueZ cache for %s: %s", address, out.decode(errors="replace").strip()[-80:])
    except Exception as e:
        log.info("could not clear BlueZ cache for %s: %s", address, e)


async def main():
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    st = load_state()
    pairing_agent = await BlueZPairingAgent.start()
    await bluez_diag(st)
    report(st, "scanning")
    fails, device = 0, None
    while True:
        try:
            report(st, "scanning")
            device = await wait_for_phone(st)
            log.info("Pokémon GO found: %s", device.address)
            report(st, "connecting")
            result, name = await handle(device, st, pairing_agent)
            fails = 0
            report(st, f"{result}", name)
            await asyncio.sleep(SUCCESS_DELAY)
        except Exception as e:
            log.error("failed (%s): %s", type(e).__name__, e, exc_info=log.isEnabledFor(logging.DEBUG))
            report(st, "failed", str(e))
            # Do not automatically remove the phone from BlueZ on every failure.
            # That can discard bond/cache state and trigger repeated iOS pairing prompts.
            # Keep the device record; stale-service recovery should be an explicit,
            # targeted diagnostic step rather than a side effect of any exchange error.
            wait = BACKOFF[min(fails, len(BACKOFF) - 1)]
            fails += 1
            log.info("waiting %.0f s before trying again (%d failures in a row)", wait, fails)
            await asyncio.sleep(wait)


if __name__ == "__main__":
    asyncio.run(main())
