import tempfile
import unittest
from pathlib import Path

from content_loader import load_mod_drafts
from game_core import TechniqueBalancer, TechniqueDraft, load_draft, save_draft, special_attack


class BalanceTests(unittest.TestCase):
    def test_all_archetypes_stay_inside_competitive_limits(self):
        for archetype in TechniqueBalancer.VALID_ARCHETYPES:
            for value in (1, 5, 10):
                tech = TechniqueBalancer.balance(
                    TechniqueDraft(archetype=archetype, power=value, reach=value, speed=value, control=value)
                )
                self.assertGreaterEqual(tech.damage, 15)
                self.assertLessEqual(tech.damage, 38)
                self.assertGreaterEqual(tech.startup, 0.11)
                self.assertLessEqual(tech.recovery, 0.58)
                self.assertGreaterEqual(tech.balance_rating, 72)
                self.assertLessEqual(tech.balance_rating, 100)

    def test_maxed_build_gets_real_tradeoffs(self):
        maxed = TechniqueBalancer.balance(TechniqueDraft(power=10, reach=10, speed=10, control=10))
        fair = TechniqueBalancer.balance(TechniqueDraft(power=6, reach=6, speed=6, control=6))
        self.assertGreater(maxed.aura_cost, fair.aura_cost)
        self.assertGreater(maxed.cooldown, fair.cooldown)
       self.assertIn("offset", maxed.balance_note)

    def test_special_copies_balanced_frame_data(self):
        tech = TechniqueBalancer.balance(TechniqueDraft(name="Testowa Aura"))
        attack = special_attack(tech)
        self.assertEqual(attack.name, "Testowa Aura")
        self.assertEqual(attack.damage, tech.damage)
        self.assertEqual(attack.reach, tech.reach)
        self.assertAlmostEqual(attack.total_time, attack.startup + attack.active + attack.recovery)

    def test_draft_round_trip(self):
        original = TechniqueDraft(name="Smoczy Rytm", archetype="mobility", color_index=3)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "technique.json"
            save_draft(target, original)
            self.assertEqual(load_draft(target), original)

    def test_mod_pack_loads_and_clamps_untrusted_values(self):
        payload = '''{
          "format": 1,
          "techniques": [{
            "name": "Mod Test", "archetype": "projectile",
            "power": 99, "reach": -4, "speed": 6, "control": 5,
            "color_index": 8
          }]
        }'''
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "test.huntermod.json"
            target.write_text(payload, encoding="utf-8")
            drafts, warnings = load_mod_drafts(Path(directory))
            self.assertFalse(warnings)
            self.assertEqual(len(drafts), 1)
            self.assertEqual(drafts[0].power, 10)
            self.assertEqual(drafts[0].reach, 1)
            self.assertEqual(drafts[0].color_index, 4)


if __name__ == "__main__":
    unittest.main()
