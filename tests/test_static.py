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

    def test_both_indication_subscriptions_use_shared_helper(self):
        main = (ROOT / "coinbag" / "main.py").read_text()
        self.assertIn('await start_indications(client, U["indicateData"], on_indication)', main)
        self.assertIn('await start_indications(client, U["indicateStage"], on_indication)', main)
        self.assertIn('bluez={"use_start_notify": True}', main)

    def test_bleak_range_supports_start_notify_override(self):
        dockerfile = (ROOT / "coinbag" / "Dockerfile").read_text()
        self.assertIn('"bleak==2.1.1"', dockerfile)


    def test_missing_go_protocol_characteristic_clears_only_target_device_cache(self):
        main = (ROOT / "coinbag" / "main.py").read_text()
        self.assertIn('client.services.get_characteristic(U["readProtocol"]) is None', main)
        self.assertIn("await forget(device.address)", main)
        self.assertIn('async def forget(address):', main)

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
