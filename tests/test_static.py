"""Lightweight static regression checks for the Coin Bag HA add-on."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AddonStaticTests(unittest.TestCase):
    def test_notify_mode_is_configurable_and_defaults_to_safe_auto(self):
        main = (ROOT / "coinbag" / "main.py").read_text()
        config = (ROOT / "coinbag" / "config.yaml").read_text()
        run = (ROOT / "coinbag" / "run.sh").read_text()
        self.assertIn('NOTIFY_MODE = os.environ.get("NOTIFY_MODE", "auto")', main)
        self.assertIn("notify_mode: auto", config)
        self.assertIn("notify_mode: list(auto|start)", config)
        self.assertIn("export LOG_LEVEL ADAPTER NOTIFY_MODE", run)

    def test_esphome_transport_is_optional_and_has_secret_api_key_option(self):
        main = (ROOT / "coinbag" / "main.py").read_text()
        config = (ROOT / "coinbag" / "config.yaml").read_text()
        run = (ROOT / "coinbag" / "run.sh").read_text()
        dockerfile = (ROOT / "coinbag" / "Dockerfile").read_text()
        self.assertIn('TRANSPORT = os.environ.get("TRANSPORT", "bluez")', main)
        self.assertIn('transport: bluez', config)
        self.assertIn('esphome_noise_psk: password?', config)
        self.assertIn("ESPHOME_ADDRESS", run)
        self.assertIn("ESPHOME_NOISE_PSK", run)
        self.assertIn('"bleak-esphome==3.9.1"', dockerfile)
        self.assertIn('version: "0.1.15"', config)

    def test_esp32_c3_example_enables_pairing_capable_proxy_without_wifi_secrets(self):
        proxy = (ROOT / "coinbag" / "esp32-c3-proxy.example.yaml").read_text()
        self.assertIn("variant: esp32c3", proxy)
        self.assertIn("bluetooth_proxy:\n  active: true", proxy)
        self.assertIn("cache_services: false", proxy)
        self.assertIn("key: !secret coinbag_esphome_api_key", proxy)
        self.assertIn("password: !secret coinbag_setup_ap_password", proxy)
        self.assertNotIn("wifi_ssid", proxy)
        self.assertNotIn("wifi_password", proxy)

    def test_proxy_manager_starts_before_scanning_and_bluez_agent_is_optional(self):
        main = (ROOT / "coinbag" / "main.py").read_text()
        self.assertIn("await habluetooth.BluetoothManager().async_setup()", main)
        self.assertIn("await manager.start()", main)
        self.assertIn('await wait_for_phone(st, TRANSPORT)', main)
        self.assertIn("if pairing_agent is not None:\n            pairing_agent.clear_target_device()", main)
        self.assertIn('if transport == "bluez":\n        adapter = pick_adapter()', main)

    def test_both_indication_subscriptions_use_shared_helper(self):
        main = (ROOT / "coinbag" / "main.py").read_text()
        self.assertIn('await start_indications(client, U["indicateData"], on_indication, transport)', main)
        self.assertIn('await start_indications(client, U["indicateStage"], on_indication, transport)', main)
        self.assertIn('bluez={"use_start_notify": True}', main)

    def test_bleak_range_supports_start_notify_override(self):
        dockerfile = (ROOT / "coinbag" / "Dockerfile").read_text()
        self.assertIn('"bleak==2.1.1"', dockerfile)


    def test_connect_wait_allows_slow_phone_connection(self):
        main = (ROOT / "coinbag" / "main.py").read_text()
        self.assertIn("CONNECT_TIMEOUT = 30.0", main)
        self.assertIn("BleakClient(device, timeout=CONNECT_TIMEOUT", main)
        self.assertIn("GATT_TIMEOUT = 10.0", main)

    def test_pairing_success_resumes_scanning_promptly(self):
        main = (ROOT / "coinbag" / "main.py").read_text()
        self.assertIn("PAIRING_DELAY = 3.0", main)
        self.assertIn('delay = PAIRING_DELAY if result == "paired" else SUCCESS_DELAY', main)
        self.assertIn("await asyncio.sleep(delay)", main)

    def test_missing_go_protocol_characteristic_removes_only_target_device_record(self):
        main = (ROOT / "coinbag" / "main.py").read_text()
        agent = (ROOT / "coinbag" / "pairing_agent.py").read_text()
        self.assertIn('client.services.get_characteristic(U["readProtocol"]) is None', main)
        self.assertIn("await pairing_agent.remove_device(device_path)", main)
        self.assertIn('member="RemoveDevice"', agent)
        self.assertNotIn("async def forget(address):", main)

    def test_go_connection_prefers_low_energy_bearer(self):
        main = (ROOT / "coinbag" / "main.py").read_text()
        agent = (ROOT / "coinbag" / "pairing_agent.py").read_text()
        self.assertLess(
            main.index("await pairing_agent.prefer_low_energy_bearer(device_path)"),
            main.index("async with BleakClient("),
        )
        self.assertIn('member="Set"', agent)
        self.assertIn('body=["org.bluez.Device1", "PreferredBearer", Variant("s", "le")]', agent)

    def test_pairing_agent_is_scoped_and_uses_just_works_capability(self):
        main = (ROOT / "coinbag" / "main.py").read_text()
        agent = (ROOT / "coinbag" / "pairing_agent.py").read_text()
        self.assertIn("pair=True", main)
        self.assertIn("await BlueZPairingAgent.start()", main)
        self.assertIn('body=[AGENT_PATH, "NoInputNoOutput"]', agent)
        self.assertIn("is_target_device(self._target_path, device_path)", agent)
        self.assertIn("org.bluez.Error.Rejected", agent)


if __name__ == "__main__":
    unittest.main()
