"""Focused safety regressions for the standalone missing-file repair."""
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

from recover_windows_snapshots import extended, recover


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cache = extended(Path(self.temporary.name) / "cache")
        self.case = {"case_id": "pytest-case", "repo": "pytest-dev/pytest", "commit": "a" * 40}
        name = "pytest-dev__pytest-" + "a" * 40
        archive = self.cache / "archives" / (name + ".tar.gz")
        archive.parent.mkdir(parents=True)
        with tarfile.open(archive, "w:gz") as stream:
            for path, raw in [("a.py", b"a = 1\n"), ("nested/b.py", b"b = 2\n")]:
                member = tarfile.TarInfo("pytest-root/" + path)
                member.size = len(raw)
                stream.addfile(member, io.BytesIO(raw))
        self.output = self.cache / "snapshots" / name
        self.output.mkdir(parents=True)
        (self.output / "a.py").write_bytes(b"a = 1\n")

    def test_only_missing_files_added_and_ordinary_verifier_accepts_marker(self):
        original = (self.output / "a.py").stat().st_mtime_ns
        plan = recover(self.case, self.cache)
        self.assertEqual(plan["missing_files"], ["nested/b.py"])
        self.assertFalse((self.output / "nested/b.py").exists())
        result = recover(self.case, self.cache, apply=True)
        self.assertEqual(result["status"], "recovered_and_verified")
        self.assertEqual(result["source_files_overwritten"], 0)
        self.assertEqual((self.output / "a.py").stat().st_mtime_ns, original)
        self.assertEqual((self.output / "nested/b.py").read_bytes(), b"b = 2\n")
        self.assertEqual(recover(self.case, self.cache)["status"], "already_verified")

    def test_mismatched_existing_source_is_preserved_and_refused_before_writes(self):
        (self.output / "a.py").write_bytes(b"user changes\n")
        with self.assertRaisesRegex(ValueError, "Mismatched"):
            recover(self.case, self.cache, apply=True)
        self.assertEqual((self.output / "a.py").read_bytes(), b"user changes\n")
        self.assertFalse((self.output / "nested/b.py").exists())
        self.assertFalse((self.output / ".graphtrust-snapshot.json").exists())

    def test_unexpected_file_is_preserved_and_refused_before_writes(self):
        (self.output / "unexpected.txt").write_bytes(b"keep me")
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            recover(self.case, self.cache, apply=True)
        self.assertEqual((self.output / "unexpected.txt").read_bytes(), b"keep me")
        self.assertFalse((self.output / "nested/b.py").exists())


if __name__ == "__main__":
    unittest.main()
