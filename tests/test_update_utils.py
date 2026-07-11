import sys
import shutil
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import update_utils


class VersionParsingTests(unittest.TestCase):
    def test_normalizes_tag_and_compares_three_part_versions(self):
        self.assertEqual(update_utils.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(update_utils.parse_version((1, 2, 3)), (1, 2, 3))
        self.assertGreater(update_utils.parse_version("v1.2.4"), (1, 2, 3))

    def test_rejects_versions_that_are_not_major_minor_patch(self):
        for value in ("1.2", "latest", "v1.2.3-beta", (1, 2)):
            with self.subTest(value=value):
                with self.assertRaises(update_utils.VersionError):
                    update_utils.parse_version(value)


class ArchiveValidationTests(unittest.TestCase):
    REQUIRED_DATA_FILES = (
        "curve_nodes.json",
        "geometry_nodes.json",
        "input_nodes.json",
        "math_nodes.json",
        "mesh_nodes.json",
        "misc_nodes.json",
    )

    @staticmethod
    def _init_text(version=(1, 0, 0)):
        return f'bl_info = {{"version": {version!r}}}\n'

    def _write_archive(self, archive_path, prefix="LearnNodeBlender_Add-on-v1.0.0", extra=None):
        def package_path(relative):
            return f"{prefix}/{relative}" if prefix else relative

        files = {
            package_path("__init__.py"): self._init_text(),
            **{
                package_path(f"data/{name}"): "{}"
                for name in self.REQUIRED_DATA_FILES
            },
        }
        files.update(extra or {})
        with zipfile.ZipFile(archive_path, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)

    def test_accepts_github_nested_root_and_validates_candidate_version(self):
        with TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            archive_path = temp / "update.zip"
            extraction_dir = temp / "extract"
            self._write_archive(archive_path)

            package_root = update_utils.extract_and_validate_archive(
                archive_path,
                extraction_dir,
                expected_version=(1, 0, 0),
                required_data_files=self.REQUIRED_DATA_FILES,
            )

            self.assertEqual(package_root.name, "LearnNodeBlender_Add-on-v1.0.0")
            self.assertTrue((package_root / "__init__.py").is_file())

    def test_accepts_package_at_extraction_root(self):
        with TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            archive_path = temp / "direct.zip"
            extraction_dir = temp / "extract"
            self._write_archive(archive_path, prefix="")

            package_root = update_utils.extract_and_validate_archive(
                archive_path,
                extraction_dir,
                expected_version=(1, 0, 0),
                required_data_files=self.REQUIRED_DATA_FILES,
            )

            self.assertEqual(package_root, extraction_dir)

    def test_rejects_path_traversal_before_installation(self):
        with TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            archive_path = temp / "unsafe.zip"
            extraction_dir = temp / "extract"
            self._write_archive(
                archive_path,
                extra={"LearnNodeBlender_Add-on-v1.0.0/../../outside.txt": "bad"},
            )

            with self.assertRaises(update_utils.ArchiveValidationError):
                update_utils.extract_and_validate_archive(
                    archive_path,
                    extraction_dir,
                    expected_version=(1, 0, 0),
                    required_data_files=self.REQUIRED_DATA_FILES,
                )
            self.assertFalse((temp / "outside.txt").exists())

    def test_rejects_candidate_version_mismatch(self):
        with TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            archive_path = temp / "wrong-version.zip"
            extraction_dir = temp / "extract"
            self._write_archive(
                archive_path,
                extra={
                    "LearnNodeBlender_Add-on-v1.0.0/__init__.py": self._init_text((2, 0, 0)),
                },
            )

            with self.assertRaises(update_utils.ArchiveValidationError):
                update_utils.extract_and_validate_archive(
                    archive_path,
                    extraction_dir,
                    expected_version=(1, 0, 0),
                    required_data_files=self.REQUIRED_DATA_FILES,
                )


class InstallTransactionTests(unittest.TestCase):
    @staticmethod
    def _copy_tree(source, target):
        shutil.copytree(source, target, dirs_exist_ok=True)

    def _make_install_fixture(self, temp):
        target = temp / "installed-addon"
        source = temp / "candidate"
        work_dir = temp / "transaction"
        target.mkdir()
        source.mkdir()
        work_dir.mkdir()
        (target / "__init__.py").write_text("old", encoding="utf-8")
        (target / "stale.py").write_text("stale", encoding="utf-8")
        (source / "__init__.py").write_text("new", encoding="utf-8")
        (source / "data").mkdir()
        (source / "data" / "new.json").write_text("{}", encoding="utf-8")
        return source, target, work_dir

    def test_success_replaces_contents_and_removes_stale_files(self):
        with TemporaryDirectory() as temp_dir:
            source, target, work_dir = self._make_install_fixture(Path(temp_dir))

            update_utils.install_package(source, target, work_dir)

            self.assertEqual((target / "__init__.py").read_text(encoding="utf-8"), "new")
            self.assertTrue((target / "data" / "new.json").is_file())
            self.assertFalse((target / "stale.py").exists())

    def test_copy_failure_restores_the_previous_installation(self):
        with TemporaryDirectory() as temp_dir:
            source, target, work_dir = self._make_install_fixture(Path(temp_dir))
            calls = 0

            def fail_during_install(source_dir, target_dir):
                nonlocal calls
                calls += 1
                if calls == 2:
                    (target_dir / "partial.py").write_text("partial", encoding="utf-8")
                    raise OSError("simulated copy failure")
                self._copy_tree(source_dir, target_dir)

            with self.assertRaises(update_utils.InstallTransactionError) as raised:
                update_utils.install_package(
                    source,
                    target,
                    work_dir,
                    copy_tree=fail_during_install,
                )

            self.assertIsNone(raised.exception.backup_path)
            self.assertEqual((target / "__init__.py").read_text(encoding="utf-8"), "old")
            self.assertTrue((target / "stale.py").is_file())
            self.assertFalse((target / "partial.py").exists())

    def test_rollback_failure_preserves_backup_path(self):
        with TemporaryDirectory() as temp_dir:
            source, target, work_dir = self._make_install_fixture(Path(temp_dir))
            calls = 0

            def fail_install_and_rollback(source_dir, target_dir):
                nonlocal calls
                calls += 1
                if calls in (2, 3):
                    raise OSError("simulated transaction failure")
                self._copy_tree(source_dir, target_dir)

            with self.assertRaises(update_utils.InstallTransactionError) as raised:
                update_utils.install_package(
                    source,
                    target,
                    work_dir,
                    copy_tree=fail_install_and_rollback,
                )

            self.assertIsNotNone(raised.exception.backup_path)
            self.assertTrue(Path(raised.exception.backup_path).is_dir())


class UpdateMetadataTests(unittest.TestCase):
    ARCHIVE_BASE = "https://codeload.github.com/char8294/LearnNodeBlender_Add-on/zip/refs/tags/"
    RELEASES_URL = "https://github.com/char8294/LearnNodeBlender_Add-on/releases"

    def test_release_metadata_uses_tag_and_release_notes(self):
        metadata = update_utils.metadata_from_release(
            {
                "tag_name": "v1.2.3",
                "html_url": "https://github.com/example/release/1.2.3",
                "body": "New geometry node explanations.",
            },
            archive_base_url=self.ARCHIVE_BASE,
            fallback_release_url=self.RELEASES_URL,
        )

        self.assertEqual(metadata.version, (1, 2, 3))
        self.assertEqual(metadata.ref, "v1.2.3")
        self.assertEqual(metadata.archive_url, self.ARCHIVE_BASE + "v1.2.3")
        self.assertEqual(metadata.release_notes, "New geometry node explanations.")
        self.assertEqual(metadata.release_url, "https://github.com/example/release/1.2.3")

    def test_tag_selection_chooses_highest_supported_numeric_tag(self):
        metadata = update_utils.metadata_from_tags(
            [
                {"name": "nightly"},
                {"name": "v1.0.0"},
                {"name": "v1.3.0"},
                {"name": "v1.2.9"},
            ],
            archive_base_url=self.ARCHIVE_BASE,
            fallback_release_url=self.RELEASES_URL,
        )

        self.assertEqual(metadata.version, (1, 3, 0))
        self.assertEqual(metadata.ref, "v1.3.0")
        self.assertEqual(metadata.release_notes, "")
        self.assertEqual(metadata.release_url, self.RELEASES_URL)

    def test_invalid_release_metadata_is_rejected(self):
        with self.assertRaises(update_utils.MetadataError):
            update_utils.metadata_from_release(
                {"tag_name": "nightly"},
                archive_base_url=self.ARCHIVE_BASE,
                fallback_release_url=self.RELEASES_URL,
            )

    def test_release_request_failure_falls_back_to_tags(self):
        requested_urls = []

        def fake_fetch(url):
            requested_urls.append(url)
            if url.endswith("/releases/latest"):
                raise TimeoutError("simulated timeout")
            return [{"name": "v1.4.0"}]

        metadata = update_utils.fetch_update_metadata(
            fake_fetch,
            release_api_url="https://api.github.com/repos/example/repo/releases/latest",
            tags_api_url="https://api.github.com/repos/example/repo/tags",
            archive_base_url=self.ARCHIVE_BASE,
            fallback_release_url=self.RELEASES_URL,
        )

        self.assertEqual(metadata.version, (1, 4, 0))
        self.assertEqual(len(requested_urls), 2)


if __name__ == "__main__":
    unittest.main()
