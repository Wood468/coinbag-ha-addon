"""Behavior checks for the scoped BlueZ pairing policy."""
from pathlib import Path
from types import SimpleNamespace
import unittest
import sys

from dbus_fast import DBusError, MessageType
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "coinbag"))

from pairing_agent import BlueZPairingAgent, CoinBagAgent, bluez_device_path, is_target_device

TARGET = "/org/bluez/hci1/dev_6E_86_AF_37_D5_F4"
OTHER = "/org/bluez/hci1/dev_00_11_22_33_44_55"


class PairingAgentTests(unittest.TestCase):
    def test_agent_accepts_authorization_only_for_active_target(self):
        agent = CoinBagAgent()
        agent.set_target_device(TARGET)
        agent.RequestAuthorization(TARGET)
        with self.assertRaises(DBusError):
            agent.RequestAuthorization(OTHER)

    def test_agent_refuses_numeric_confirmation_without_a_user_display(self):
        agent = CoinBagAgent()
        agent.set_target_device(TARGET)
        with self.assertRaises(DBusError):
            agent.RequestConfirmation(TARGET, 123456)

    def test_scanned_device_path_is_used_when_available(self):
        device = SimpleNamespace(address="6E:86:AF:37:D5:F4", details={"path": TARGET})
        self.assertEqual(bluez_device_path(device, "hci1"), TARGET)

    def test_device_path_falls_back_to_address_and_selected_adapter(self):
        device = SimpleNamespace(address="6e:86:af:37:d5:f4", details={})
        self.assertEqual(bluez_device_path(device, "hci1"), TARGET)

    def test_pairing_policy_matches_only_exact_current_target(self):
        self.assertTrue(is_target_device(TARGET, TARGET))
        self.assertFalse(is_target_device(TARGET, OTHER))
        self.assertFalse(is_target_device(None, TARGET))



class FakeBus:
    def __init__(self):
        self.message = None

    async def call(self, message):
        self.message = message
        return SimpleNamespace(message_type=MessageType.METHOD_RETURN)


class PairingAgentRemovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_remove_device_calls_owning_adapter_with_exact_device_path(self):
        bus = FakeBus()
        interface = CoinBagAgent()
        interface.set_target_device(TARGET)
        agent = BlueZPairingAgent(bus, interface)

        await agent.remove_device(TARGET)

        self.assertEqual(bus.message.destination, "org.bluez")
        self.assertEqual(bus.message.path, "/org/bluez/hci1")
        self.assertEqual(bus.message.interface, "org.bluez.Adapter1")
        self.assertEqual(bus.message.member, "RemoveDevice")
        self.assertEqual(bus.message.signature, "o")
        self.assertEqual(bus.message.body, [TARGET])

    async def test_remove_device_rejects_a_different_active_target(self):
        bus = FakeBus()
        interface = CoinBagAgent()
        interface.set_target_device(TARGET)
        agent = BlueZPairingAgent(bus, interface)

        with self.assertRaises(DBusError):
            await agent.remove_device(OTHER)

        self.assertIsNone(bus.message)


if __name__ == "__main__":
    unittest.main()
