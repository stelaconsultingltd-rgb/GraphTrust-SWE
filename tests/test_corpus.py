from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error

from graphtrust.corpus import DATASET, download, fetch_corpus, patch_files, prepare_snapshot, select_cases


class CorpusTests(unittest.TestCase):
    def test_gold_excludes_test_changes_and_deduplicates(self):
        patch = '+++ b/src/a.py\n+++ b/tests/test_a.py\n+++ b/src/a.py\n+++ /dev/null\n+++ b/src/conftest.py\n'
        self.assertEqual(patch_files(patch), ['src/a.py'])

    def test_selection_is_hash_based_repo_disjoint_and_gold_independent(self):
        cases = [{"case_id": f"r-{n}", "repo": "r/r", "split": "test", "patch": str(n)} for n in range(9)]
        cases += [{"case_id": "dev", "repo": "other/repo", "split": "dev"}]
        eligible = {c['case_id']: {'eligible': True} for c in cases}
        protocol = {'holdout_repositories': ['r/r'], 'holdout_per_repository': 3, 'sampling_seed': 17}
        first = select_cases(cases, eligible, protocol, 'test')
        for case in cases:
            case['patch'] = 'changed answer'
        second = select_cases(list(reversed(cases)), eligible, protocol, 'test')
        self.assertEqual(first['selection_hash'], second['selection_hash'])
        self.assertEqual(len(first['cases']), 3)
        self.assertFalse(first['uses_gold'])

    def test_selection_discloses_missing_preparations_and_shortfall(self):
        cases = [{'case_id': 'a', 'repo': 'r/r', 'split': 'test'}]
        result = select_cases(cases, {}, {'holdout_repositories': ['r/r'], 'holdout_per_repository': 10, 'sampling_seed': 1}, 'test')
        self.assertEqual(result['shortfalls']['r/r']['available'], 0)
        self.assertEqual(result['exclusions'][0]['reason'], 'not_prepared')


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.cache = Path(temporary.name)
        self.case = {"repo": "owner/repo", "commit": "a" * 40}
        self.name = "owner__repo-" + "a" * 40
        self.archive = self.cache / "archives" / (self.name + ".tar.gz")
        self.archive.parent.mkdir()
        with tarfile.open(self.archive, "w:gz") as stream:
            for name, raw in {"repo/main.py": b"def f():\n    pass\n", "repo/pkg/LICENSE": b"upstream license\n",
                              "repo/README.md": b"not graph input"}.items():
                member = tarfile.TarInfo(name)
                member.size = len(raw)
                stream.addfile(member, io.BytesIO(raw))

    @staticmethod
    def marker(snapshot):
        return snapshot / ".graphtrust-snapshot.json"

    def test_manifest_is_complete_and_resume_checks_source_and_license(self):
        snapshot = prepare_snapshot(self.case, self.cache)
        record = json.loads(self.marker(snapshot).read_text())
        self.assertEqual(record["schema_version"], 2)
        self.assertEqual(set(record["files"]), {"main.py", "pkg/LICENSE"})
        self.assertFalse((snapshot / "README.md").exists())
        self.assertEqual(prepare_snapshot(self.case, self.cache), snapshot)
        for name in record["files"]:
            file = snapshot / name
            original = file.read_bytes()
            file.write_bytes(b"user change")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "checksum mismatch"):
                prepare_snapshot(self.case, self.cache)
            self.assertEqual(file.read_bytes(), b"user change")
            file.write_bytes(original)

    def test_added_and_removed_python_files_invalidate_without_reset(self):
        snapshot = prepare_snapshot(self.case, self.cache)
        extra = snapshot / "extra.py"
        extra.write_text("# user file")
        with self.assertRaisesRegex(ValueError, "selected-file set mismatch"):
            prepare_snapshot(self.case, self.cache)
        self.assertEqual(extra.read_text(), "# user file")
        extra.unlink()
        (snapshot / "main.py").unlink()
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            prepare_snapshot(self.case, self.cache)
        self.assertFalse((snapshot / "main.py").exists())

    def test_legacy_marker_upgrades_from_original_archive_and_keeps_source_bytes(self):
        snapshot = prepare_snapshot(self.case, self.cache)
        marker = self.marker(snapshot)
        record = json.loads(marker.read_text())
        record.pop("files")
        record.pop("schema_version")
        marker.write_text(json.dumps(record))
        before = (snapshot / "main.py").stat().st_mtime_ns
        prepare_snapshot(self.case, self.cache)
        upgraded = json.loads(marker.read_text())
        self.assertEqual(upgraded["schema_version"], 2)
        self.assertEqual(set(upgraded["files"]), {"main.py", "pkg/LICENSE"})
        self.assertEqual((snapshot / "main.py").stat().st_mtime_ns, before)

    def test_legacy_marker_does_not_bless_modified_source(self):
        snapshot = prepare_snapshot(self.case, self.cache)
        marker = self.marker(snapshot)
        record = json.loads(marker.read_text())
        record.pop("files")
        marker.write_text(json.dumps(record))
        (snapshot / "main.py").write_text("# changed by user")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            prepare_snapshot(self.case, self.cache)
        self.assertNotIn("files", json.loads(marker.read_text()))
        self.assertEqual((snapshot / "main.py").read_text(), "# changed by user")

    def test_archive_and_repository_identity_are_checked(self):
        snapshot = prepare_snapshot(self.case, self.cache)
        marker = self.marker(snapshot)
        record = json.loads(marker.read_text())
        record["repo"] = "different/repo"
        marker.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "repository/commit mismatch"):
            prepare_snapshot(self.case, self.cache)
        record["repo"] = self.case["repo"]
        marker.write_text(json.dumps(record))
        self.archive.write_bytes(b"modified archive")
        with self.assertRaisesRegex(ValueError, "archive checksum mismatch"):
            prepare_snapshot(self.case, self.cache)

    def test_concurrent_workers_wait_and_reuse_one_completed_snapshot(self):
        from graphtrust import corpus
        original = corpus._archive_files
        entered, release = threading.Event(), threading.Event()
        def held_extract(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise AssertionError("test failed to release extraction")
            return original(*args, **kwargs)
        with patch("graphtrust.corpus._archive_files", side_effect=held_extract) as extract, ThreadPoolExecutor(2) as pool:
            first = pool.submit(prepare_snapshot, self.case, self.cache)
            self.assertTrue(entered.wait(3))
            second = pool.submit(prepare_snapshot, self.case, self.cache)
            time.sleep(0.05)
            self.assertFalse(second.done())
            release.set()
            self.assertEqual(first.result(), second.result())
            self.assertEqual(extract.call_count, 1)
        self.assertFalse(list((self.cache / "snapshot-locks").glob("*.lock")))

    def test_unsafe_archive_path_is_rejected_without_writing_outside_snapshot(self):
        with tarfile.open(self.archive, "w:gz") as stream:
            member = tarfile.TarInfo("repo/../../outside.py")
            member.size = 4
            stream.addfile(member, io.BytesIO(b"evil"))
        with self.assertRaisesRegex(ValueError, "Unsafe archive"):
            prepare_snapshot(self.case, self.cache)
        self.assertFalse((self.cache / "outside.py").exists())
        self.assertFalse(list((self.cache / "snapshot-locks").glob("*.lock")))

    def test_symlink_snapshot_file_is_rejected_and_target_preserved(self):
        snapshot = prepare_snapshot(self.case, self.cache)
        outside = self.cache / "outside.py"
        outside.write_text("# preserve outside")
        file = snapshot / "main.py"
        file.unlink()
        try:
            os.symlink(outside, file)
        except OSError as exc:
            self.skipTest(f"Symlink creation unavailable: {exc}")
        with self.assertRaisesRegex(ValueError, "Symlink/junction"):
            prepare_snapshot(self.case, self.cache)
        self.assertEqual(outside.read_text(), "# preserve outside")

    def test_invalid_identifier_is_rejected_before_any_cache_write(self):
        for case in ({"repo": "../owner/repo", "commit": "a" * 40},
                     {"repo": "owner/repo", "commit": "main"},
                     {"repo": None, "commit": "a" * 40}):
            with self.subTest(case=case), self.assertRaises(ValueError):
                prepare_snapshot(case, self.cache)
        self.assertFalse((self.cache / "snapshots").exists())


class DownloadTests(unittest.TestCase):
    class Response(io.BytesIO):
        def __init__(self, raw, advertised=None):
            super().__init__(raw)
            self.headers = {"Content-Length": str(len(raw) if advertised is None else advertised)}

    def test_partial_response_retries_from_zero_and_leaves_no_staging_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "archive.bin"
            responses = [self.Response(b"abc", 6), self.Response(b"abcdef")]
            with patch("graphtrust.corpus.urllib.request.urlopen", side_effect=responses) as urlopen, patch("graphtrust.corpus.time.sleep"):
                checksum = download("https://example.test/archive", destination)
            self.assertEqual(urlopen.call_count, 2)
            self.assertEqual(destination.read_bytes(), b"abcdef")
            self.assertEqual(checksum, hashlib.sha256(b"abcdef").hexdigest())
            self.assertFalse(list(Path(directory).glob("*.part")))

    def test_nonretryable_http_failure_preserves_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "archive.bin"
            destination.write_bytes(b"previous verified bytes")
            error = urllib.error.HTTPError("https://example.test", 403, "Forbidden", {}, None)
            self.addCleanup(error.close)
            with patch("graphtrust.corpus.urllib.request.urlopen", side_effect=error) as urlopen, self.assertRaises(urllib.error.HTTPError):
                download("https://example.test/archive", destination)
            self.assertEqual(urlopen.call_count, 1)
            self.assertEqual(destination.read_bytes(), b"previous verified bytes")
            self.assertFalse(list(Path(directory).glob("*.part")))

    def test_fetch_reuses_only_a_consistent_pinned_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "evaluator").mkdir()
            files = {"cases.jsonl": b"cases\n", "evaluator/gold.jsonl": b"private gold\n"}
            for name, raw in files.items():
                (root / name).write_bytes(raw)
            lock = {"dataset": DATASET, "revision": "a" * 40,
                    "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}}
            (root / "dataset-lock.json").write_text(json.dumps(lock))
            with patch("graphtrust.corpus.urllib.request.urlopen") as urlopen:
                self.assertEqual(fetch_corpus(root), lock)
                urlopen.assert_not_called()
            (root / "evaluator/gold.jsonl").write_bytes(b"modified")
            with self.assertRaisesRegex(ValueError, "Corpus checksum mismatch"):
                fetch_corpus(root)
            self.assertFalse((root / ".graphtrust-fetch.lock").exists())


if __name__ == '__main__':
    unittest.main()
