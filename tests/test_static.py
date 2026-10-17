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
        self.assertIn('"bleak>=2.1.1,<3.0"', dockerfile)


if __name__ == "__main__":
    unittest.main()
