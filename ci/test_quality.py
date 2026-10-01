"""Focused regression tests for generated template outputs."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import quality


class GeneratedOutputValidationTests(unittest.TestCase):
    def test_signal_terminated_parser_output_is_not_a_completed_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            script = (
                "import os, signal; "
                "print('parse error: expected expression', flush=True); "
                "os.kill(os.getpid(), signal.SIGTERM)"
            )
            with self.assertRaises(quality.QualityFailure) as raised:
                quality._run_cli(
                    sys.executable,
                    ["-c", script],
                    cwd=Path(temp_dir),
                    stage="analysis",
                )

            self.assertEqual(raised.exception.category, "parser")
            self.assertFalse(raised.exception.completed)

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

    def test_quality_self_check_rejects_non_parser_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            failure = quality.QualityFailure("analysis", "runtime", "timed out")
            with patch("quality._run_cli", side_effect=failure):
                with self.assertRaisesRegex(quality.QualityFailure, "parser diagnostic"):
                    quality._verify_invalid_fixture("/fake/beskid", Path(temp_dir))

    def test_quality_self_check_accepts_completed_parser_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            failure = quality.QualityFailure(
                "analysis", "parser", "parse error: expected expression", completed=True
            )
            with patch("quality._run_cli", side_effect=failure):
                quality._verify_invalid_fixture("/fake/beskid", Path(temp_dir))

    def test_quality_self_check_rejects_timeout_even_with_parser_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            failure = quality.QualityFailure(
                "analysis", "parser", "parse error then timed out", completed=False
            )
            with patch("quality._run_cli", side_effect=failure):
                with self.assertRaisesRegex(quality.QualityFailure, "completed parser diagnostic"):
                    quality._verify_invalid_fixture("/fake/beskid", Path(temp_dir))

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

    def test_template_authoring_root_requires_a_generated_project_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = root / "Authoring.bproj"
            manifest.write_text('Authoring {\n  name = "Authoring"\n  type = Template\n}\n', encoding="utf-8")

            with self.assertRaisesRegex(quality.QualityFailure, "missing generated Project.lock"):
                quality._validate_template_authoring_lock_contract(root, manifest, "/fake/beskid", root)

    def test_template_authoring_root_rejects_a_lock_owned_by_another_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = root / "Authoring.bproj"
            manifest.write_text('Authoring {\n  name = "Authoring"\n  type = Template\n}\n', encoding="utf-8")
            (root / "Project.lock").write_text(
                "# Project.lock v2\nroot_manifest=Other.bproj\nproject_name=Other\ndependencies:\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(quality.QualityFailure, "root_manifest must name 'Authoring.bproj'"):
                quality._validate_template_authoring_lock_contract(root, manifest, "/fake/beskid", root)

    def test_template_authoring_root_rejects_a_lock_with_the_wrong_corelib_closure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            corelib = root / "corelib"
            self._write_corelib_fixture(corelib, with_runtime=True)
            manifest = root / "Authoring.bproj"
            manifest.write_text('Authoring {\n  name = "Authoring"\n  type = Template\n}\n', encoding="utf-8")
            lock = root / "Project.lock"
            lock.write_text(
                "# Project.lock v2\n"
                "root_manifest=Authoring.bproj\n"
                "project_name=Authoring\n"
                "dependencies:\n"
                "- name=Std;source=corelib;project=beskid_corelib;manifest=corelib.bproj;source_root=.;materialized_root=obj/beskid/deps/src/Std-0123456789abcdef0123456789abcdef\n",
                encoding="utf-8",
            )
            self._materialize_corelib_fixture(lock, corelib)

            with self.assertRaisesRegex(quality.QualityFailure, "closure does not match supplied Corelib"):
                quality._validate_template_authoring_lock_contract(root, manifest, "/fake/beskid", corelib)

    def test_template_authoring_root_validates_lock_provenance_and_runs_locked_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            corelib = root / "corelib"
            self._write_corelib_fixture(corelib, with_runtime=True)
            manifest = root / "Authoring.bproj"
            manifest.write_text('Authoring {\n  name = "Authoring"\n  type = Template\n}\n', encoding="utf-8")
            lock = root / "Project.lock"
            lock.write_text(
                "# Project.lock v2\n"
                "root_manifest=Authoring.bproj\n"
                "project_name=Authoring\n"
                "dependencies:\n"
                "- name=Std;source=corelib;project=beskid_corelib;manifest=corelib.bproj;source_root=.;materialized_root=obj/beskid/deps/src/Std-0123456789abcdef0123456789abcdef\n"
                "- name=corelib_runtime;source=corelib;project=packages/runtime;manifest=corelib_runtime.bproj;source_root=src;materialized_root=obj/beskid/deps/src/runtime-0123456789abcdef0123456789abcdef\n",
                encoding="utf-8",
            )
            self._materialize_corelib_fixture(lock, corelib)

            with patch("quality._run_cli") as run_cli:
                quality._validate_template_authoring_lock_contract(root, manifest, "/candidate/beskid", corelib)

            run_cli.assert_called_once_with(
                "/candidate/beskid",
                ["fetch", "--project", str(manifest), "--locked", "--plain"],
                cwd=root,
                stage="lock-replay",
            )

    def test_lock_corelib_closure_must_match_the_supplied_corelib_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            verified = base / "verified-corelib"
            wrong = base / "wrong-corelib"
            self._write_corelib_fixture(verified, with_runtime=True)
            self._write_corelib_fixture(wrong, with_runtime=False)
            lock = base / "Project.lock"
            lock.write_text(
                "# Project.lock v2\n"
                "root_manifest=App.bproj\n"
                "project_name=App\n"
                "dependencies:\n"
                "- name=Std;source=corelib;project=beskid_corelib;manifest=corelib.bproj;source_root=.;materialized_root=obj/beskid/deps/src/Std-0123456789abcdef0123456789abcdef\n"
                "- name=corelib_runtime;source=corelib;project=packages/runtime;manifest=corelib_runtime.bproj;source_root=src;materialized_root=obj/beskid/deps/src/runtime-0123456789abcdef0123456789abcdef\n",
                encoding="utf-8",
            )
            self._materialize_corelib_fixture(lock, verified)

            quality._validate_corelib_lock(lock, verified)
            with self.assertRaisesRegex(quality.QualityFailure, "closure does not match supplied Corelib"):
                quality._validate_corelib_lock(lock, wrong)

    def test_template_authoring_root_rejects_materialized_sources_from_another_corelib_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            supplied = base / "supplied-corelib"
            alternate = base / "alternate-corelib"
            self._write_corelib_fixture(supplied, with_runtime=True)
            self._write_corelib_fixture(alternate, with_runtime=True)
            (supplied / "packages/runtime/src/Runtime.bd").write_text("module Runtime { fn Value() -> i32 { 1 } }\n", encoding="utf-8")
            (alternate / "packages/runtime/src/Runtime.bd").write_text("module Runtime { fn Value() -> i32 { 2 } }\n", encoding="utf-8")

            output = base / "generated-project"
            output.mkdir()
            manifest = output / "Authoring.bproj"
            manifest.write_text('Authoring {\n  name = "Authoring"\n  type = Template\n}\n', encoding="utf-8")
            materialized_std = output / "obj/beskid/deps/src/Std-0123456789abcdef0123456789abcdef"
            materialized_runtime = output / "obj/beskid/deps/src/runtime-0123456789abcdef0123456789abcdef"
            materialized_std.mkdir(parents=True)
            materialized_runtime.mkdir(parents=True)
            (materialized_std / "corelib.bproj").write_text(
                (supplied / "beskid_corelib/corelib.bproj").read_text(encoding="utf-8"), encoding="utf-8"
            )
            (materialized_runtime / "src").mkdir()
            (materialized_runtime / "corelib_runtime.bproj").write_text(
                (supplied / "packages/runtime/corelib_runtime.bproj").read_text(encoding="utf-8"), encoding="utf-8"
            )
            (materialized_runtime / "src/Runtime.bd").write_text(
                (supplied / "packages/runtime/src/Runtime.bd").read_text(encoding="utf-8"), encoding="utf-8"
            )

            lock = output / "Project.lock"
            lock.write_text(
                "# Project.lock v2\n"
                "root_manifest=Authoring.bproj\n"
                "project_name=Authoring\n"
                "dependencies:\n"
                "- name=Std;source=corelib;project=beskid_corelib;manifest=corelib.bproj;source_root=.;materialized_root=obj/beskid/deps/src/Std-0123456789abcdef0123456789abcdef\n"
                "- name=corelib_runtime;source=corelib;project=packages/runtime;manifest=corelib_runtime.bproj;source_root=src;materialized_root=obj/beskid/deps/src/runtime-0123456789abcdef0123456789abcdef\n",
                encoding="utf-8",
            )

            with patch("quality._run_cli"):
                quality._validate_template_authoring_lock_contract(output, manifest, "/fake/beskid", supplied)
            with self.assertRaisesRegex(quality.QualityFailure, "materialized Corelib sources do not match supplied Corelib"):
                quality._validate_template_authoring_lock_contract(output, manifest, "/fake/beskid", alternate)

    def test_corelib_provenance_ignores_unreachable_missing_workspace_members(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "corelib"
            self._write_corelib_fixture(root, with_runtime=True)
            workspace = root / "CoreLib.bws"
            workspace.write_text(
                workspace.read_text(encoding="utf-8")
                + '\nmember "dev_tool" {\n  path = "mods/dev_tool"\n  package = "corelib_dev_tool"\n}\n',
                encoding="utf-8",
            )

            closure = quality._corelib_dependency_closure(root)

            self.assertEqual(
                closure,
                {
                    ("Std", "beskid_corelib", "corelib.bproj", "."),
                    ("corelib_runtime", "packages/runtime", "corelib_runtime.bproj", "src"),
                },
            )

    @staticmethod
    def _write_corelib_fixture(root: Path, *, with_runtime: bool) -> None:
        (root / "beskid_corelib").mkdir(parents=True)
        (root / "beskid_corelib" / "corelib.bproj").write_text(
            'corelib {\n  name = "corelib"\n  type = Aggregate\n' + (
                '  dependency "corelib_runtime" {\n    source = "path"\n    path = "../packages/runtime"\n  }\n'
                if with_runtime
                else ""
            ) + "}\n",
            encoding="utf-8",
        )
        workspace_members = ['member "corelib" {\n  path = "beskid_corelib"\n  package = "corelib"\n}']
        if with_runtime:
            runtime = root / "packages" / "runtime"
            (runtime / "src").mkdir(parents=True)
            (runtime / "corelib_runtime.bproj").write_text(
                'corelib_runtime {\n  name = "corelib_runtime"\n  root = "src"\n}\n',
                encoding="utf-8",
            )
            workspace_members.append('member "runtime" {\n  path = "packages/runtime"\n  package = "corelib_runtime"\n}')
        (root / "CoreLib.bws").write_text(
            'workspace {\n  name = "corelib"\n}\n' + "\n".join(workspace_members) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _materialize_corelib_fixture(lock: Path, corelib_root: Path) -> None:
        for row in quality._read_lock_dependencies(lock):
            if row["source"] != "corelib":
                continue
            source_project = corelib_root / row["project"]
            if quality._project_field((source_project / row["manifest"]).read_text(encoding="utf-8"), "type") == "Aggregate":
                continue
            source = source_project / row["source_root"]
            destination = lock.parent / row["materialized_root"] / row["source_root"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, destination, symlinks=True)

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
