"""Regression: missing store sections must never count as stable loading evidence."""
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "pogo-store-reader" / "store_snapshot.py"
spec = importlib.util.spec_from_file_location("snapshot_empty_stability", SOURCE)
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


class EmptyStabilityTests(unittest.TestCase):
    def test_repeated_empty_section_census_fails_closed_at_cap(self):
        passes, stable, sections = snapshot.scroll_until_stable(
            lambda: [], lambda: None, max_passes=5, stable_needed=2
        )
        self.assertEqual((passes, stable, sections), (5, 0, []))
        self.assertFalse(snapshot.build_completeness(passes, stable, 5, sections)["loadComplete"])

    def test_sections_arriving_after_empty_passes_require_fresh_stability(self):
        observations = [[], [], [{"name": "boxes", "count": 3}],
                        [{"name": "boxes", "count": 3}], [{"name": "boxes", "count": 3}]]
        n = [0]
        def scroll():
            n[0] += 1
        def read():
            return observations[n[0] - 1]
        passes, stable, sections = snapshot.scroll_until_stable(read, scroll, max_passes=8)
        self.assertEqual((passes, stable), (5, 2))
        self.assertEqual(sections, observations[-1])

    def test_empty_sections_between_valid_passes_reset_stability(self):
        observations = [[{"name": "boxes", "count": 3}],
                        [{"name": "boxes", "count": 3}], [],
                        [{"name": "boxes", "count": 3}],
                        [{"name": "boxes", "count": 3}],
                        [{"name": "boxes", "count": 3}]]
        n = [0]
        def scroll():
            n[0] += 1
        passes, stable, _ = snapshot.scroll_until_stable(
            lambda: observations[n[0] - 1], scroll, max_passes=8
        )
        self.assertEqual((passes, stable), (6, 2))


if __name__ == "__main__":
    unittest.main()
