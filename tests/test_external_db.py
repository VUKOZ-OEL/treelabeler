"""Testy prace s externi SQLite (raycloudtools trees).

Novy model: labels zijou v ODDELENE .labels.sqlite databazích. Raycloudtools
sqlite s tabulkou `trees` je otevrena read-only pres ATTACH a nikdy se do ni
nezapisuje.
"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from treelabeler.db import Database  # noqa: E402


def make_ext_sqlite(path: Path):
    con = sqlite3.connect(str(path))
    con.execute("""
        CREATE TABLE trees (
            fid INTEGER PRIMARY KEY, x REAL, y REAL, z REAL, height REAL,
            crown_radius REAL, dist2dmt REAL, section_id REAL
        )
    """)
    con.executemany(
        "INSERT INTO trees (fid,x,y,z,height,crown_radius,dist2dmt,section_id) VALUES (?,?,?,?,?,?,?,?)",
        [(1, 100.0, 200.0, 500.0, 12.0, 2.5, -0.5, 5.0),
         (2, 101.0, 201.0, 499.0, 10.0, 1.5, 0.25, 7.0),
         (3, 102.0, 202.0, 498.0, 8.0,  1.0, 0.0, 9.0)],
    )
    con.commit(); con.close()


class TestExternalDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.trees_path = self.dir / "projekt.laz.sqlite"
        make_ext_sqlite(self.trees_path)
        self.labels_path = self.dir / "projekt.labels.sqlite"
        self.db = Database(self.labels_path, data_dir=self.dir,
                           trees_db_path=self.trees_path)
        self.db.sync_categories([
            {"name": "Coniferous", "group": "tree_type"},
            {"name": "Broadleaf", "group": "tree_type"},
            {"name": "Not a tree", "group": "tree_type"},
            {"name": "Complete", "group": "quality"},
            {"name": "Missing part", "group": "quality"},
        ])

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_trees_path_is_separate_from_labels(self):
        # labels DB a trees DB jsou RUZNE soubory
        self.assertNotEqual(self.db.db_path.resolve(), self.db.trees_db_path.resolve())

    def test_is_external(self):
        self.assertTrue(self.db.external)
        self.assertEqual(len(self.db._trees), 3)

    def test_trees_db_kept_intact_after_label(self):
        # predzapisene trees DB se nesmi zmenit zapisem labelu
        before = self.trees_path.stat_st_size if hasattr(self.trees_path, 'stat_st_size') else self.trees_path.stat().st_size
        f = self.dir / "cloud_segmented_7.laz"; f.touch()
        fid = self.db.upsert_file(f, 50)
        self.db.set_label(fid, tree_type="Broadleaf", quality="Complete")
        after = self.trees_path.stat().st_size
        self.assertEqual(before, after)
        con = sqlite3.connect(str(self.trees_path))
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        con.close()
        self.assertEqual(tables, {"trees"})         # zadne nove tabulky pridane

    def test_parse_section_id(self):
        self.assertEqual(Database.parse_section_id("cloud_segmented_123.laz"), 123)
        self.assertEqual(Database.parse_section_id("cloud_segmented_-1.laz"), -1)
        self.assertIsNone(Database.parse_section_id("foo.laz"))
        self.assertIsNone(Database.parse_section_id("cloud_segmented_X.laz"))

    def test_verify_pairing(self):
        laz = ["cloud_segmented_5.laz", "cloud_segmented_7.laz",
               "cloud_segmented_-1.laz", "cloud_segmented_999.laz"]
        rep = self.db.verify_pairing(laz)
        self.assertEqual(sorted(rep["known"]), [5, 7])
        self.assertEqual(rep["new_trees"], [999])
        self.assertEqual(rep["orphan_trees"], [9])

    def test_dist2dmt_exposed_in_get_file(self):
        f = self.dir / "cloud_segmented_5.laz"; f.touch()
        fid = self.db.upsert_file(f, 100)
        self.assertEqual(fid, 5)
        rec = self.db.get_file(fid)
        self.assertEqual(rec["section_id"], 5)
        self.assertEqual(rec["tree_id"], 5)
        self.assertEqual(rec["dist2dmt"], -0.5)

    def test_labels_write_goes_to_labels_db_not_trees(self):
        f = self.dir / "cloud_segmented_7.laz"; f.touch()
        fid = self.db.upsert_file(f, 50)
        self.db.set_label(fid, tree_type="Broadleaf", quality="Complete")
        con = sqlite3.connect(str(self.labels_path))
        rows = con.execute(
            "SELECT f.tree_id, f.filename, c1.name, c2.name "
            "FROM labels l JOIN files f ON f.tree_id=l.tree_id "
            "LEFT JOIN categories c1 ON c1.id=l.category_id "
            "LEFT JOIN categories c2 ON c2.id=l.quality_category_id"
        ).fetchall()
        con.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], (7, "cloud_segmented_7.laz", "Broadleaf", "Complete"))

    def test_upsert_refuses_minus1(self):
        with self.assertRaises(ValueError):
            self.db.upsert_file(self.dir / "cloud_segmented_-1.laz", None)

    def test_pairing_keeps_minus1_out_of_all_categories(self):
        laz = ["cloud_segmented_5.laz", "cloud_segmented_-1.laz", "foo.laz"]
        rep = self.db.verify_pairing(laz)
        self.assertNotIn(-1, rep["known"]); self.assertNotIn(-1, rep["new_trees"])
        self.assertNotIn(-1, rep["orphan_trees"])
        self.assertNotIn("cloud_segmented_-1.laz", rep["unparsable"])

    def test_scans_skip_minus1(self):
        from treelabeler.server import _scan_dir
        for n in ("cloud_segmented_5.laz", "cloud_segmented_-1.laz", "cloud_segmented_7.laz"):
            (self.dir / n).touch()
        _scan_dir(self.db, self.dir, count_points=False)
        names = [f["filename"] for f in self.db.list_files()]
        self.assertIn("cloud_segmented_5.laz", names)
        self.assertIn("cloud_segmented_7.laz", names)
        self.assertNotIn("cloud_segmented_-1.laz", names)


class TestLegacyDbStaysNonExternal(unittest.TestCase):
    def test_empty_dir_creates_non_external(self):
        tmp = tempfile.TemporaryDirectory()
        d = Path(tmp.name) / "data"; d.mkdir()
        db = Database(d / "data.db", data_dir=d)
        self.assertFalse(db.external)
        self.assertIsNone(db.get_tree_meta(5))
        db.close(); tmp.cleanup()

    def test_close_detaches_and_can_be_called_twice(self):
        # close reportedly must not crash and must not leak the attach
        tmp = tempfile.TemporaryDirectory()
        d = Path(tmp.name) / "data"; d.mkdir()
        trees_path = d / "x.laz.sqlite"
        trees_con = sqlite3.connect(str(trees_path))
        trees_con.execute("CREATE TABLE trees (section_id REAL, x REAL)")
        trees_con.execute("INSERT INTO trees VALUES (1.0, 5.0)")
        trees_con.commit(); trees_con.close()
        db = Database(d / "x.labels.sqlite", data_dir=d, trees_db_path=trees_path)
        db.close()
        db.close()      # druhy close nesmi hodit
        tmp.cleanup()


class TestSingleFileMode(unittest.TestCase):
    """Rezim, kdy treelabeler pracuje primo v raycloudtools .laz.sqlite —
    doplnuji se files/categories/labels vedle tabulky trees."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.trees_path = self.dir / "proj.laz.sqlite"
        make_ext_sqlite(self.trees_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_opens_and_labels_in_same_file(self):
        db = Database(self.trees_path, data_dir=self.dir, trees_db_path=None)
        self.assertTrue(db.external)
        self.assertEqual(len(db._trees), 3)
        db.sync_categories([
            {"name": "Coniferous", "group": "tree_type"},
            {"name": "Complete", "group": "quality"},
        ])
        f = self.dir / "cloud_segmented_5.laz"; f.touch()
        tid = db.upsert_file(f, None)
        db.set_label(tid, tree_type="Coniferous", quality="Complete")
        db.close()
        # po restaru se label nacte z tehoz souboru
        db2 = Database(self.trees_path, data_dir=self.dir, trees_db_path=None)
        self.assertTrue(db2.external)
        rec = db2.get_file(5)
        self.assertEqual(rec["tree_type"], "Coniferous")
        self.assertEqual(rec["quality"], "Complete")
        self.assertEqual(rec["dist2dmt"], -0.5)
        db2.close()

    def test_labels_stay_in_same_file_across_restarts(self):
        db = Database(self.trees_path, data_dir=self.dir)
        db.sync_categories([{"name": "Coniferous", "group": "tree_type"},
                            {"name": "Complete", "group": "quality"}])
        (self.dir / "cloud_segmented_7.laz").touch()
        db.upsert_file(self.dir / "cloud_segmented_7.laz", None)
        db.set_label(7, tree_type="Coniferous", quality="Complete")
        db.close()
        db2 = Database(self.trees_path, data_dir=self.dir)
        # existujici label se pri bootstrapu nacte (progress)
        p = db2.progress()
        self.assertEqual(p["labeled"], 1)
        self.assertEqual(p["total"], 1)
        db2.close()


if __name__ == "__main__":
    unittest.main()
