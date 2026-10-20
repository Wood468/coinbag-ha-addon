from pathlib import Path
from types import ModuleType
import importlib.util
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_main_with_stub_dependencies():
    fake_bleak = ModuleType("bleak")
    fake_bleak.BleakClient = object
    fake_bleak.BleakScanner = object
    fake_protocol = ModuleType("protocol")
    fake_protocol.UUIDS = {"advertisementService": "test-service"}
    fake_pairing_agent = ModuleType("pairing_agent")
    fake_pairing_agent.BlueZPairingAgent = object
    fake_pairing_agent.bluez_device_path = lambda device, adapter: ""

    main_path = ROOT / "coinbag" / "main.py"
    spec = importlib.util.spec_from_file_location("coinbag_main_test", main_path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        "bleak": fake_bleak,
        "protocol": fake_protocol,
        "pairing_agent": fake_pairing_agent,
    }):
        spec.loader.exec_module(module)
    return module


coinbag_main = load_main_with_stub_dependencies()


class ESPHomeProxySetupTests(unittest.IsolatedAsyncioTestCase):
    async def test_proxy_manager_receives_address_and_encryption_key_after_bluetooth_setup(self):
        events = []
        config = {}

        class FakeBluetoothManager:
            async def async_setup(self):
                events.append("bluetooth_setup")

        class FakeAPIConnectionManager:
            def __init__(self, received_config):
                config.update(received_config)
                events.append("manager_created")

            async def start(self):
                events.append("manager_started")

        fake_habluetooth = ModuleType("habluetooth")
        fake_habluetooth.BluetoothManager = FakeBluetoothManager
        fake_bleak_esphome = ModuleType("bleak_esphome")
        fake_bleak_esphome.APIConnectionManager = FakeAPIConnectionManager

        with (
            patch.object(coinbag_main, "ESPHOME_ADDRESS", "192.0.2.10"),
            patch.object(coinbag_main, "ESPHOME_NOISE_PSK", "test-key"),
            patch.dict(sys.modules, {
                "habluetooth": fake_habluetooth,
                "bleak_esphome": fake_bleak_esphome,
            }),
        ):
            manager = await coinbag_main.start_esphome_proxy()

        self.assertIsInstance(manager, FakeAPIConnectionManager)
        self.assertEqual(config, {"address": "192.0.2.10", "noise_psk": "test-key"})
        self.assertEqual(events, ["bluetooth_setup", "manager_created", "manager_started"])

    async def test_proxy_transport_requires_an_address(self):
        with (
            patch.object(coinbag_main, "ESPHOME_ADDRESS", ""),
            self.assertRaisesRegex(RuntimeError, "requires an ESPHome proxy address"),
        ):
            await coinbag_main.start_esphome_proxy()

    async def test_proxy_transport_requires_api_encryption(self):
        with (
            patch.object(coinbag_main, "ESPHOME_ADDRESS", "192.0.2.10"),
            patch.object(coinbag_main, "ESPHOME_NOISE_PSK", ""),
            self.assertRaisesRegex(RuntimeError, "requires the proxy's API encryption key"),
        ):
            await coinbag_main.start_esphome_proxy()


if __name__ == "__main__":
    unittest.main()
