"""A device-scoped BlueZ pairing agent for Pokémon GO GATT connections."""
import logging
import re

from bleak.backends.bluezdbus.manager import get_global_bluez_manager
from dbus_fast import DBusError, Message, MessageType
from dbus_fast.service import ServiceInterface, method

log = logging.getLogger("coinbag")
BLUEZ = "org.bluez"
AGENT_MANAGER = "org.bluez.AgentManager1"
AGENT_PATH = "/org/coinbag/agent"
AGENT_INTERFACE = "org.bluez.Agent1"


def is_target_device(active_path: str | None, requested_path: str) -> bool:
    """Only authorize the exact device Coin Bag selected from the GO advertisement."""
    return bool(active_path) and active_path == requested_path


def bluez_device_path(device, adapter: str) -> str:
    """Return BlueZ’s object path for a scanned BLEDevice."""
    details = getattr(device, "details", None)
    path = details.get("path") if hasattr(details, "get") else None
    if isinstance(path, str) and path.startswith("/org/bluez/"):
        return path
    address = getattr(device, "address", None)
    if not address:
        raise ValueError("Scanned Bluetooth device has no address or BlueZ object path")
    normalized_address = address.upper().replace(":", "_")
    return f"/org/bluez/{adapter}/dev_{normalized_address}"


class CoinBagAgent(ServiceInterface):
    """Handle security callbacks only for the active Pokémon GO peripheral."""

    def __init__(self):
        super().__init__(AGENT_INTERFACE)
        self._target_path: str | None = None

    def set_target_device(self, device_path: str) -> None:
        self._target_path = device_path

    def clear_target_device(self) -> None:
        self._target_path = None

    def _require_target(self, device_path: str, action: str) -> None:
        if not is_target_device(self._target_path, device_path):
            log.warning("rejecting Bluetooth %s request for non-target device %s", action, device_path)
            raise DBusError("org.bluez.Error.Rejected", "Coin Bag only pairs with the active Pokémon GO device")

    @method()
    def Release(self):
        log.warning("BlueZ released the Coin Bag pairing agent")

    @method()
    def RequestAuthorization(self, device: "o"):
        self._require_target(device, "authorization")
        log.info("authorized Just Works pairing for the active Pokémon GO device")

    @method()
    def RequestConfirmation(self, device: "o", passkey: "u"):
        self._require_target(device, "numeric confirmation")
        # NoInputNoOutput should negotiate Just Works. Refuse numeric comparison because
        # there is no screen on which the user can verify that the passkey matches.
        log.error("BlueZ requested numeric confirmation for the active phone; refusing unverifiable passkey")
        raise DBusError("org.bluez.Error.Rejected", "Coin Bag cannot verify a numeric Bluetooth passkey")

    @method()
    def RequestPinCode(self, device: "o") -> "s":
        self._require_target(device, "PIN entry")
        raise DBusError("org.bluez.Error.Rejected", "PIN entry is not supported")

    @method()
    def RequestPasskey(self, device: "o") -> "u":
        self._require_target(device, "passkey entry")
        raise DBusError("org.bluez.Error.Rejected", "Passkey entry is not supported")

    @method()
    def DisplayPinCode(self, device: "o", pincode: "s"):
        self._require_target(device, "PIN display")

    @method()
    def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):
        self._require_target(device, "passkey display")

    @method()
    def AuthorizeService(self, device: "o", uuid: "s"):
        self._require_target(device, "service authorization")

    @method()
    def Cancel(self):
        log.debug("BlueZ cancelled a pairing-agent request")


class BlueZPairingAgent:
    """Register an app-specific agent on the same D-Bus connection used by Bleak."""

    def __init__(self, bus, interface: CoinBagAgent):
        self._bus = bus
        self._interface = interface

    @classmethod
    async def start(cls):
        # Sharing Bleak’s bus makes this the agent for the same D-Bus application that calls Pair().
        manager = await get_global_bluez_manager()
        bus = manager._bus
        if bus is None or not bus.connected:
            raise RuntimeError("Bleak BlueZ D-Bus connection is unavailable for pairing-agent registration")

        interface = CoinBagAgent()
        bus.export(AGENT_PATH, interface)
        reply = await bus.call(Message(
            destination=BLUEZ,
            path="/org/bluez",
            interface=AGENT_MANAGER,
            member="RegisterAgent",
            signature="os",
            body=[AGENT_PATH, "NoInputNoOutput"],
        ))
        if reply.message_type == MessageType.ERROR:
            bus.unexport(AGENT_PATH, AGENT_INTERFACE)
            detail = reply.body[0] if reply.body else reply.error_name
            raise RuntimeError(f"BlueZ could not register the scoped pairing agent: {detail}")
        log.info("registered scoped BlueZ pairing agent (NoInputNoOutput)")
        return cls(bus, interface)

    def set_target_device(self, device_path: str) -> None:
        self._interface.set_target_device(device_path)

    def clear_target_device(self) -> None:
        self._interface.clear_target_device()

    async def remove_device(self, device_path: str) -> None:
        """Remove only the active GO device record using the adapter in its BlueZ path."""
        self._interface._require_target(device_path, "cache removal")
        if not re.fullmatch(r"/org/bluez/hci[0-9]+/dev_[0-9A-Fa-f_]+", device_path):
            raise ValueError(f"Invalid BlueZ device object path: {device_path}")

        adapter_path = device_path.rsplit("/", 1)[0]
        reply = await self._bus.call(Message(
            destination=BLUEZ,
            path=adapter_path,
            interface="org.bluez.Adapter1",
            member="RemoveDevice",
            signature="o",
            body=[device_path],
        ))
        if reply.message_type == MessageType.ERROR:
            if reply.error_name == "org.bluez.Error.DoesNotExist":
                log.info("BlueZ device record already absent: %s", device_path)
                return
            detail = reply.body[0] if reply.body else reply.error_name
            raise RuntimeError(f"BlueZ could not remove cached device {device_path}: {detail}")
        log.info("removed BlueZ device record for stale GATT cache: %s", device_path)

    async def close(self) -> None:
        reply = await self._bus.call(Message(
            destination=BLUEZ,
            path="/org/bluez",
            interface=AGENT_MANAGER,
            member="UnregisterAgent",
            signature="o",
            body=[AGENT_PATH],
        ))
        if reply.message_type == MessageType.ERROR and reply.error_name != "org.bluez.Error.DoesNotExist":
            log.warning("failed to unregister BlueZ pairing agent: %s", reply.body)
        self._bus.unexport(AGENT_PATH, AGENT_INTERFACE)
        log.info("unregistered scoped BlueZ pairing agent")
