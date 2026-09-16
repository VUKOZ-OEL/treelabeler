"""API testy. Soubory pro testy se vytvareji jako cloud_segmented_<N>.laz
kvuli nulove tree_id zacinajici od nuly (section_id)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient  # noqa: E402
from treelabeler.server import create_app  # noqa: E402


class TestApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "data"
        self.root.mkdir()
        for n, name in enumerate(["cloud_segmented_0.laz", "cloud_segmented_1.laz",
                                  "cloud_segmented_-1.laz"] if False else
                                 ["cloud_segmented_0.laz", "cloud_segmented_1.laz"]):
            (self.root / name).touch()
        # cloud_segmented_-1.laz existuje na disku, ale nesmi se nahrat
        (self.root / "cloud_segmented_-1.laz").touch()
        self.app = create_app(self.root)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.app.state.db.close()
        self.tmp.cleanup()

    def test_minus1_skipped_always(self):
        r = self.client.get("/api/files")
        names = [f["filename"] for f in r.json()["files"]]
        self.assertEqual(len(names), 2)
        self.assertNotIn("cloud_segmented_-1.laz", names)

    def test_bootstrap_has_groups_and_categories(self):
        r = self.client.get("/api/bootstrap")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data["files"]), 2)
        self.assertEqual(data["progress"], {"total": 2, "labeled": 0})
        groups = {g["id"] for g in data["groups"]}
        self.assertEqual(groups, {"tree_type", "quality"})
        names = {c["name"] for c in data["categories"]}
        self.assertIn("Coniferous", names)
        self.assertIn("Multitree", names)
        self.assertTrue(all(c.get("group") for c in data["categories"]))

    def test_label_both_slots_and_next(self):
        files = self.client.get("/api/files").json()["files"]
        f0 = files[0]
        self.assertEqual(f0["tree_id"], 0)
        r = self.client.post("/api/label", json={"file_id": f0["id"], "tree_type": "Coniferous"})
        self.assertTrue(r.json()["ok"])
        self.assertEqual(r.json()["progress"]["labeled"], 0)
        self.assertEqual(r.json()["next_file_id"], f0["id"])
        r = self.client.post("/api/label", json={"file_id": f0["id"], "quality": "Complete"})
        self.assertTrue(r.json()["ok"])
        self.assertEqual(r.json()["progress"]["labeled"], 1)
        self.assertEqual(r.json()["next_file_id"], files[1]["id"])

    def test_unparsable_filename_rejected_implicitly(self):
        # soubory neodpovidajici cloud_segmented_<n> se nenahraji (behem scanu raise)
        (self.root / "random.laz").touch()
        from treelabeler.server import _scan_dir
        with self.assertRaises(ValueError):
            _scan_dir(self.app.state.db, self.root, count_points=False)

    def test_export_csv_has_tree_id_first_column(self):
        files = self.client.get("/api/files").json()["files"]
        self.client.post("/api/label", json={"file_id": files[0]["id"],
                                             "tree_type": "Broadleaf",
                                             "quality": "Multitree"})
        r = self.client.get("/api/export.csv")
        self.assertEqual(r.status_code, 200)
        lines = r.text.splitlines()
        self.assertEqual(lines[0], "tree_id,filename,abs_path,tree_type,quality")
        self.assertIn("0,cloud_segmented_0.laz", lines[1])
        self.assertIn("Broadleaf,Multitree", lines[1])


if __name__ == "__main__":
    unittest.main()
