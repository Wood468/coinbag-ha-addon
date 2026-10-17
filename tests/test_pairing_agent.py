"""Behavior checks for the scoped BlueZ pairing policy."""
from pathlib import Path
from types import SimpleNamespace
import unittest
import sys

from dbus_fast import DBusError
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "coinbag"))

from pairing_agent import CoinBagAgent, bluez_device_path, is_target_device

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


if __name__ == "__main__":
    unittest.main()
