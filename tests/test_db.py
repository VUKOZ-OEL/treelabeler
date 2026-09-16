import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from treelabeler.db import Database  # noqa: E402


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.db.sync_categories([
            {"name": "Coniferous", "group": "tree_type", "shortcut": "1"},
            {"name": "Broadleaf", "group": "tree_type", "shortcut": "2"},
            {"name": "Complete", "group": "quality", "shortcut": "1"},
            {"name": "Missing part", "group": "quality", "shortcut": "2"},
            {"name": "Excessive part", "group": "quality", "shortcut": "3"},
            {"name": "Multitree", "group": "quality", "shortcut": "4"},
        ])

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def _touch(self, n: int) -> Path:
        p = Path(self.tmp.name) / f"cloud_segmented_{n}.laz"
        p.touch()
        return p

    def test_categories_have_groups(self):
        cats = self.db.list_categories()
        groups = {c["name"]: c["group"] for c in cats}
        self.assertEqual(groups["Coniferous"], "tree_type")
        self.assertEqual(groups["Multitree"], "quality")

    def test_both_slots_label_flow(self):
        fid = self.db.upsert_file(self._touch(0), 10)
        self.assertEqual(fid, 0)
        self.assertEqual(self.db.progress()["labeled"], 0)
        self.assertEqual(self.db.next_unlabeled_id(), 0)
        self.db.set_label(0, tree_type="Coniferous")
        self.assertEqual(self.db.progress()["labeled"], 0)
        self.assertEqual(self.db.next_unlabeled_id(), 0)
        self.db.set_label(0, quality="Complete")
        self.assertEqual(self.db.progress()["labeled"], 1)
        self.assertIsNone(self.db.next_unlabeled_id())

    def test_label_upsert_preserves_other_slot(self):
        fid = self.db.upsert_file(self._touch(7), 1)
        self.assertEqual(fid, 7)
        self.db.set_label(7, tree_type="Broadleaf", quality="Complete")
        rec = self.db.get_file(7)
        self.assertEqual(rec["tree_type"], "Broadleaf")
        self.assertEqual(rec["quality"], "Complete")
        self.db.set_label(7, quality="Multitree")
        rec = self.db.get_file(7)
        self.assertEqual(rec["tree_type"], "Broadleaf")
        self.assertEqual(rec["quality"], "Multitree")

    def test_next_unlabeled_skips_fully_labeled(self):
        i1 = self.db.upsert_file(self._touch(3), None)
        i2 = self.db.upsert_file(self._touch(4), None)
        self.assertEqual(self.db.next_unlabeled_id(), i1)
        self.db.set_label(i1, tree_type="Coniferous", quality="Complete")
        self.assertEqual(self.db.next_unlabeled_id(), i2)

    def test_list_files_returns_both_columns(self):
        fid = self.db.upsert_file(self._touch(11), 5)
        self.db.set_label(fid, tree_type="Coniferous", quality="Excessive part")
        rows = self.db.list_files()
        self.assertEqual(rows[0]["tree_type"], "Coniferous")
        self.assertEqual(rows[0]["quality"], "Excessive part")
        self.assertEqual(rows[0]["tree_id"], 11)
        self.assertEqual(rows[0]["id"], 11)   # legacy alias musi fungovat

    def test_upsert_refuses_minus1(self):
        with self.assertRaises(ValueError):
            self.db.upsert_file(self._touch(-1), None)

    def test_upsert_refuses_unparsable(self):
        with self.assertRaises(ValueError):
            self.db.upsert_file(Path(self.tmp.name) / "random.laz", None)


if __name__ == "__main__":
    unittest.main()
