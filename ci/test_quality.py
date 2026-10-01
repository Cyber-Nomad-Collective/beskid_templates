"""Focused regression tests for generated template outputs."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import quality


class GeneratedOutputValidationTests(unittest.TestCase):
    def test_unresolved_tokens_are_found_in_paths_and_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            token_dir = root / "{{folder}}"
            token_dir.mkdir()
            token_file = token_dir / "{{name}}.bd"
            token_file.write_text("fn {{name}}() {}\n", encoding="utf-8")

            self.assertTrue(hasattr(quality, "_find_unresolved_tokens"))
            unresolved = quality._find_unresolved_tokens(root)

            self.assertEqual(
                unresolved,
                ["{{folder}}", "{{folder}}/{{name}}.bd", "{{folder}}/{{name}}.bd:content"],
            )

    def test_lock_root_manifest_is_read_from_v2_header_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock = Path(temp_dir) / "Project.lock"
            lock.write_text(
                "# Project.lock v2\nroot_manifest=Starter.bproj\nproject_name=Starter\n",
                encoding="utf-8",
            )

            self.assertTrue(hasattr(quality, "_read_lock_root_manifest"))
            self.assertEqual(quality._read_lock_root_manifest(lock), "Starter.bproj")

    def test_lock_root_manifest_decodes_project_lock_v2_path_escapes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock = Path(temp_dir) / "Project.lock"
            lock.write_text(
                "# Project.lock v2\nroot_manifest=%7B%7Bname%7D%7D.bproj\n",
                encoding="utf-8",
            )

            self.assertEqual(quality._read_lock_root_manifest(lock), "{{name}}.bproj")

    def test_lock_without_root_manifest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock = Path(temp_dir) / "Project.lock"
            lock.write_text("# Project.lock v2\nproject_name=Starter\n", encoding="utf-8")

            self.assertTrue(hasattr(quality, "_read_lock_root_manifest"))
            with self.assertRaisesRegex(ValueError, "root_manifest"):
                quality._read_lock_root_manifest(lock)

    def test_quality_self_check_rejects_a_cli_that_accepts_invalid_source(self) -> None:
        self.assertTrue(hasattr(quality, "_verify_invalid_fixture"))
        with tempfile.TemporaryDirectory() as temp_dir:
            seen: dict[str, str] = {}

            def inspect_fixture(_cli: str, arguments: list[str], **_kwargs: object) -> None:
                fixture = next(Path(argument) for argument in arguments if argument.endswith(".bd"))
                seen["content"] = fixture.read_text(encoding="utf-8")

            with patch("quality._run_cli", side_effect=inspect_fixture) as run_cli:
                with self.assertRaisesRegex(quality.QualityFailure, "accepted intentionally invalid"):
                    quality._verify_invalid_fixture("/fake/beskid", Path(temp_dir))
            run_cli.assert_called_once()
            self.assertEqual(seen["content"], "fn Main( -> i32 { return 0; }\n")

    def test_missing_library_entrypoint_is_classified_as_semantic_analysis(self) -> None:
        self.assertTrue(hasattr(quality, "_failure_category"))
        self.assertEqual(
            quality._failure_category("build", "Error: Missing entrypoint `Main`"),
            "semantic analysis",
        )

    def test_item_template_targets_the_host_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            host = Path(temp_dir) / "host"
            host.mkdir()
            manifest = host / "Host.bproj"
            manifest.write_text("Host { name = \"Host\" }\n", encoding="utf-8")
            captured: dict[str, list[str]] = {}

            def inspect_cli(_cli: str, arguments: list[str], **_kwargs: object) -> None:
                captured["arguments"] = arguments

            with patch("quality._run_cli", side_effect=inspect_cli):
                quality._generate_item_template(
                    "/fake/beskid",
                    "packages/contract-item",
                    host,
                    manifest,
                    "QualityContract",
                )

            arguments = captured["arguments"]
            self.assertEqual(arguments[arguments.index("--output") + 1], str(host))
            self.assertEqual(arguments[arguments.index("--project") + 1], str(manifest))

    def test_generated_manifest_must_use_the_requested_name_in_file_and_content(self) -> None:
        self.assertTrue(hasattr(quality, "_validate_generated_manifest"))
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = Path(temp_dir) / "QualityApp.bproj"
            manifest.write_text(
                'QualityApp {\n  name = "QualityApp"\n}\n',
                encoding="utf-8",
            )

            quality._validate_generated_manifest(manifest, "QualityApp")
            with self.assertRaisesRegex(quality.QualityFailure, "requested name"):
                quality._validate_generated_manifest(manifest, "OtherApp")


if __name__ == "__main__":
    unittest.main()
