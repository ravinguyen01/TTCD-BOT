import unittest

from classbot.mock import MockStore


class MockStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = MockStore(":memory:")
        for code in ("A", "B"):
            self.store.add_class(code)
            self.store.roster(code, [{"uid": "101", "username": "old-name"}])

    def test_same_uid_can_have_independent_class_records(self):
        self.assertTrue(self.store.attendance("A", ["101"], "2026-11-15"))
        self.assertTrue(self.store.attendance("B", [], "2026-11-15"))
        self.assertEqual(self.store.report("A", "2026-11-15")[0]["attendance"], "Có mặt")
        self.assertEqual(self.store.report("B", "2026-11-15")[0]["attendance"], "Vắng")

    def test_repeated_attendance_refreshes_current_day(self):
        self.assertTrue(self.store.attendance("A", ["101"], "2026-11-15"))
        self.assertTrue(self.store.attendance("A", [], "2026-11-15"))
        self.assertEqual(self.store.report("A", "2026-11-15")[0]["attendance"], "Vắng")

    def test_roster_removal_and_rejoin_preserve_history(self):
        self.store.attendance('A',['101'],'2026-11-15')
        self.store.roster('A',[])
        self.assertEqual(self.store.report('A','2026-11-15'),[])
        self.store.roster('A',[{'uid':'101','username':'restored','display_name':'Display Name'}])
        row=self.store.report('A','2026-11-15')[0]
        self.assertEqual(row['attendance'],'Có mặt')
        self.assertEqual(row['display_name'],'Display Name')

    def test_points_are_additive_but_interaction_is_unique(self):
        self.assertTrue(self.store.add_points("A", "101", 2, "900", "i1", "2026-11-15"))
        self.assertFalse(self.store.add_points("A", "101", 2, "900", "i1", "2026-11-15"))
        self.assertTrue(self.store.add_points("A", "101", 3, "900", "i2", "2026-11-15"))
        self.assertEqual(self.store.report("A", "2026-11-15")[0]["points"], 5)
        self.assertIsNone(self.store.report("B", "2026-11-15")[0]["points"])

    def test_roster_updates_name_without_losing_history(self):
        self.store.attendance("A", ["101"], "2026-11-15")
        self.store.roster("A", [{"uid": "101", "username": "new-name"}])
        row = self.store.report("A", "2026-11-15")[0]
        self.assertEqual(row["username"], "new-name")
        self.assertEqual(row["attendance"], "Có mặt")


if __name__ == "__main__":
    unittest.main()
