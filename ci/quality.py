"""Quality checks for the Beskid first-party templates workspace."""

from __future__ import annotations

import json
import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_MANIFEST = ROOT / "beskid_templates.bws"
WORKSPACE_PACKAGE_JSON = ROOT / "workspace.package.json"

TEMPLATE_MEMBERS: tuple[tuple[str, str, str, str], ...] = (
    ("console", "packages/console", "beskid_templates_console", "beskid.templates.console"),
    ("lib", "packages/lib", "beskid_templates_lib", "beskid.templates.lib"),
    ("project", "packages/project", "beskid_templates_project", "beskid.templates.project"),
    (
        "workspace_demo",
        "packages/workspace-demo",
        "beskid_templates_workspace_demo",
        "beskid.templates.workspace-demo",
    ),
    ("host", "packages/host", "beskid_templates_host", "beskid.templates.host"),
    (
        "fiber_demo",
        "packages/fiber-demo",
        "beskid_templates_fiber_demo",
        "beskid.templates.fiber-demo",
    ),
    (
        "contract_item",
        "packages/contract-item",
        "beskid_templates_contract_item",
        "beskid.templates.contract-item",
    ),
)

TIMEOUT_SECONDS = 120
TOKEN = re.compile(r"\{\{[^{}]+\}\}")
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class QualityFailure(RuntimeError):
    def __init__(self, stage: str, category: str, details: str) -> None:
        super().__init__(details)
        self.stage = stage
        self.category = category

FORBIDDEN_CORELIB_OPTOUT = re.compile(
    r"\b(noCorelib|useCorelib\s*:\s*false)\b",
    re.IGNORECASE,
)

REQUIRED_TEMPLATE_KEYS = frozenset(
    {"schema", "identity", "name", "shortName"},
)

VALID_TAG_TYPES = frozenset({"project", "workspace", "item"})


def _project_field(content: str, key: str) -> str | None:
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        current_key, value = line.split("=", 1)
        if current_key.strip() == key:
            return value.strip().strip('"')
    return None


def _load_template_json(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"template.json root must be an object: {path}")
    return data


def _validate_template_manifest(path: Path, expected_identity_prefix: str) -> None:
    data = _load_template_json(path)
    schema = data.get("schema")
    if schema != "beskid.template.v1":
        raise SystemExit(f"{path}: schema must be beskid.template.v1, got {schema!r}")

    missing = REQUIRED_TEMPLATE_KEYS - set(data)
    if missing:
        raise SystemExit(f"{path}: missing required keys: {sorted(missing)}")

    identity = str(data["identity"])
    if not identity.startswith(expected_identity_prefix):
        raise SystemExit(
            f"{path}: identity must start with {expected_identity_prefix!r}, got {identity!r}"
        )

    tags = data.get("tags")
    if isinstance(tags, dict):
        tag_type = tags.get("type")
        if tag_type not in VALID_TAG_TYPES:
            raise SystemExit(f"{path}: tags.type must be one of {sorted(VALID_TAG_TYPES)}, got {tag_type!r}")

    symbols = data.get("symbols")
    if symbols is not None and not isinstance(symbols, dict):
        raise SystemExit(f"{path}: symbols must be an object when present")

    sources = data.get("sources")
    if sources is not None:
        if not isinstance(sources, list):
            raise SystemExit(f"{path}: sources must be an array when present")
        for index, entry in enumerate(sources):
            if not isinstance(entry, dict):
                raise SystemExit(f"{path}: sources[{index}] must be an object")


def _scan_forbidden_corelib_optout(directory: Path) -> None:
    if not directory.is_dir():
        return
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in {".bproj", ".bd", ".md", ".json"}:
            continue
        if path.name == "template.json" and ".beskid" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if FORBIDDEN_CORELIB_OPTOUT.search(text):
            raise SystemExit(f"Forbidden corelib opt-out in generated content: {path}")


def _find_unresolved_tokens(
    directory: Path,
    *,
    allowed_prefixes: Sequence[str] = (),
) -> list[str]:
    issues: list[str] = []
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory).as_posix()
        if any(relative == prefix or relative.startswith(prefix.rstrip("/") + "/") for prefix in allowed_prefixes):
            continue
        if TOKEN.search(relative):
            issues.append(relative)
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if TOKEN.search(content):
            issues.append(f"{relative}:content")
    return issues


def _read_lock_root_manifest(lock_path: Path) -> str:
    lines = lock_path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "# Project.lock v2":
        raise ValueError(f"{lock_path}: expected Project.lock v2 header")
    for line in lines[1:]:
        key, separator, value = line.partition("=")
        if separator and key == "root_manifest" and value:
            try:
                return unquote(value, errors="strict")
            except UnicodeDecodeError as exc:
                raise ValueError(f"{lock_path}: root_manifest is not valid UTF-8") from exc
    raise ValueError(f"{lock_path}: missing root_manifest")


def _failure_category(stage: str, output: str) -> str:
    text = ANSI_ESCAPE.sub("", output).lower()
    patterns = (
        ("infrastructure", ("runtime kit", "corelib root", "corelib not found", "could not resolve corelib")),
        ("parser", ("parse error", "parser error", "syntax error", "unexpected token", "expected expression")),
        (
            "semantic analysis",
            ("semantic error", "unresolved name", "unknown type", "type mismatch", "missing entrypoint", "e20"),
        ),
        ("lowering", ("lowering failed", "isle", "codegen failed", "unsupported lowering")),
        ("linker", ("linker", "undefined symbol", "ld.lld", "link failed")),
        ("runtime", ("runtime error", "panic", "aborted", "timed out")),
    )
    for category, needles in patterns:
        if any(needle in text for needle in needles):
            return category
    return {
        "generation": "generation",
        "analysis": "semantic analysis",
        "build": "lowering",
        "run": "runtime",
    }.get(stage, stage)


def _diagnostic_excerpt(output: str) -> str:
    lines = ANSI_ESCAPE.sub("", output).strip().splitlines()
    excerpt = "\n".join(lines[-40:])
    return excerpt[-8_000:]


def _run_cli(
    cli: str,
    arguments: Sequence[str],
    *,
    cwd: Path,
    timeout: int = TIMEOUT_SECONDS,
    stage: str,
) -> None:
    command = [cli, *arguments]
    environment = os.environ.copy()
    environment.update({"NO_COLOR": "1", "TERM": "dumb"})
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        raise QualityFailure(
            stage,
            _failure_category(stage, output + " timed out"),
            f"{command!r} timed out after {timeout}s\n{_diagnostic_excerpt(output)}",
        ) from exc
    except OSError as exc:
        raise QualityFailure(stage, "infrastructure", f"cannot execute {cli}: {exc}") from exc
    if result.returncode != 0:
        raise QualityFailure(
            stage,
            _failure_category(stage, result.stdout),
            f"{command!r} exited {result.returncode}\n{_diagnostic_excerpt(result.stdout)}",
        )
    print(f"quality check: {Path(cli).name} {stage}=PASS")


def _verify_invalid_fixture(cli: str, directory: Path) -> None:
    fixture = directory / "QualityInvalid.bd"
    fixture.write_text("fn Main( -> i32 { return 0; }\n", encoding="utf-8")
    try:
        try:
            _run_cli(cli, ["analyze", str(fixture), "--plain"], cwd=directory, stage="analysis")
        except QualityFailure as failure:
            if failure.category == "infrastructure":
                raise QualityFailure("fixture", "infrastructure", f"invalid-source check could not run: {failure}") from failure
            print(f"quality fixture: intentionally invalid .bd rejected [{failure.category}]")
            return
        raise QualityFailure("fixture", "parser", "CLI accepted intentionally invalid .bd source")
    finally:
        fixture.unlink(missing_ok=True)


def _project_manifest(directory: Path) -> Path:
    manifests = sorted(directory.glob("*.bproj"))
    if len(manifests) != 1:
        raise QualityFailure("generation", "generation", f"expected one project manifest in {directory}, found {len(manifests)}")
    print(f"quality check: manifest={manifests[0].name}:PASS")
    return manifests[0]


def _validate_generated_manifest(manifest: Path, requested_name: str) -> None:
    content = manifest.read_text(encoding="utf-8")
    root_block = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*\{", content)
    project_name = _project_field(content, "name")
    if manifest.name != f"{requested_name}.bproj" or project_name != requested_name or root_block is None or root_block.group(1) != requested_name:
        raise QualityFailure(
            "generation",
            "generation",
            f"{manifest}: requested name {requested_name!r} must match its filename, root block, and name field",
        )
    print(f"quality check: project-name={requested_name}:PASS")


def _validate_generated_workspace(directory: Path, requested_name: str) -> Path:
    workspaces = sorted(directory.glob("*.bws"))
    if len(workspaces) != 1:
        raise QualityFailure("generation", "generation", f"expected one workspace manifest in {directory}, found {len(workspaces)}")
    manifest = workspaces[0]
    if manifest.name != f"{requested_name}.bws" or _project_field(manifest.read_text(encoding="utf-8"), "name") != requested_name:
        raise QualityFailure("generation", "generation", f"{manifest}: workspace name does not match {requested_name!r}")
    print(f"quality check: workspace-name={requested_name}:PASS")
    return manifest


def _ensure_manifest_and_lock(directory: Path, manifest: Path, cli: str) -> None:
    lock = directory / "Project.lock"
    if not lock.is_file():
        _run_cli(cli, ["lock", "--project", str(manifest), "--plain"], cwd=directory, stage="lock")
    try:
        owner = _read_lock_root_manifest(lock)
    except (OSError, ValueError) as exc:
        raise QualityFailure("lock", "generation", str(exc)) from exc
    if owner != manifest.name:
        raise QualityFailure(
            "lock",
            "generation",
            f"{lock}: root_manifest must name {manifest.name!r}, got {owner!r}",
        )
    print(f"quality check: lock-owner={owner}:PASS")


def _new_template(
    cli: str,
    template: str,
    output: Path,
    symbols: dict[str, str],
    *,
    primary_name: str | None = None,
    project_manifest: Path | None = None,
) -> None:
    arguments = [
        "new",
        "--path",
        str(ROOT / template),
        "--output",
        str(output),
        "--no-interactive",
        "--force",
    ]
    if project_manifest is not None:
        arguments.extend(["--project", str(project_manifest)])
    if primary_name is not None:
        arguments.extend(["--name", primary_name])
        symbols = {key: value for key, value in symbols.items() if key != "name"}
    for key, value in symbols.items():
        arguments.extend(["--symbol", f"{key}={value}"])
    _run_cli(cli, arguments, cwd=ROOT, stage="generation")


def _generate_item_template(
    cli: str,
    template: str,
    host_directory: Path,
    project_manifest: Path,
    contract_name: str,
) -> None:
    _new_template(
        cli,
        template,
        host_directory,
        {"contractName": contract_name},
        project_manifest=project_manifest,
    )


def _assert_generated_clean(directory: Path, *, allowed_prefixes: Sequence[str] = ()) -> None:
    unresolved = _find_unresolved_tokens(directory, allowed_prefixes=allowed_prefixes)
    if unresolved:
        raise QualityFailure(
            "generation",
            "generation",
            f"unresolved template tokens in {directory}: {', '.join(unresolved)}",
        )
    print(f"quality check: generated paths/content={directory.name}:PASS")


def _collect_failure(failures: list[QualityFailure], operation) -> None:
    try:
        operation()
    except QualityFailure as failure:
        failures.append(failure)
        print(f"quality check: {failure.stage}=FAIL [{failure.category}]")


def _raise_collected_failures(failures: list[QualityFailure]) -> None:
    if not failures:
        return
    categories = ", ".join(dict.fromkeys(failure.category for failure in failures))
    details = "\n".join(f"[{failure.category}] {failure}" for failure in failures)
    raise QualityFailure(failures[0].stage, categories, details)


def _check_project(
    cli: str,
    directory: Path,
    *,
    build: bool,
    run: bool,
    failures: list[QualityFailure],
    requested_name: str,
) -> Path:
    manifest = _project_manifest(directory)
    _collect_failure(failures, lambda: _validate_generated_manifest(manifest, requested_name))
    _collect_failure(failures, lambda: _ensure_manifest_and_lock(directory, manifest, cli))
    _collect_failure(
        failures,
        lambda: _run_cli(cli, ["analyze", "--project", str(manifest), "--locked", "--plain"], cwd=directory, stage="analysis"),
    )
    if build:
        _collect_failure(
            failures,
            lambda: _run_cli(cli, ["build", "--project", str(manifest), "--locked", "--plain"], cwd=directory, stage="build"),
        )
    if run:
        _collect_failure(
            failures,
            lambda: _run_cli(cli, ["run", "--project", str(manifest), "--locked", "--plain"], cwd=directory, stage="run"),
        )
    return manifest


def _template_result(name: str, operation) -> None:
    try:
        operation()
    except QualityFailure as failure:
        print(f"quality result: {name}: {failure.stage} FAIL [{failure.category}]")
        for line in str(failure).splitlines():
            print(f"  {line}")
        raise
    print(f"quality result: {name}: PASS")


def _check_generated_templates(cli: str) -> list[str]:
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="beskid-template-quality-") as temp:
        scratch = Path(temp)
        names = {
            "console": ("QualityConsoleApp",),
            "lib": ("QualityLibrary",),
            "project": ("QualityTemplateAuthoring",),
            "workspace_demo": ("QualityWorkspace",),
            "host": ("QualityHost",),
            "fiber_demo": ("QualityFiberDemo",),
            "contract_item": ("QualityContract",),
        }
        specs = {row[0]: row for row in TEMPLATE_MEMBERS}

        def run_template(member: str) -> None:
            _, source_rel, _, _ = specs[member]
            output = scratch / member
            value = names[member][0]
            failures: list[QualityFailure] = []
            if member == "workspace_demo":
                _new_template(cli, source_rel, output, {"workspaceName": value})
                _collect_failure(failures, lambda: _assert_generated_clean(output))
                _collect_failure(failures, lambda: _validate_generated_workspace(output, value))
                app_manifest = _project_manifest(output / "app")
                lib_manifest = _project_manifest(output / "lib")
                _collect_failure(failures, lambda: _validate_generated_manifest(app_manifest, f"{value}App"))
                _collect_failure(failures, lambda: _validate_generated_manifest(lib_manifest, f"{value}Lib"))
                _collect_failure(failures, lambda: _ensure_manifest_and_lock(output / "app", app_manifest, cli))
                _collect_failure(failures, lambda: _ensure_manifest_and_lock(output / "lib", lib_manifest, cli))
                _collect_failure(
                    failures,
                    lambda: _run_cli(cli, ["analyze", "--project", str(app_manifest), "--locked", "--plain"], cwd=output, stage="analysis"),
                )
                _collect_failure(
                    failures,
                    lambda: _run_cli(cli, ["build", "--project", str(app_manifest), "--locked", "--plain"], cwd=output, stage="build"),
                )
                _collect_failure(
                    failures,
                    lambda: _run_cli(cli, ["run", "--project", str(app_manifest), "--locked", "--plain"], cwd=output, stage="run"),
                )
                _raise_collected_failures(failures)
                return
            if member == "contract_item":
                host = scratch / "contract-item-host"
                _new_template(
                    cli,
                    "packages/console",
                    host,
                    {},
                    primary_name="QualityItemHost",
                )
                _collect_failure(failures, lambda: _assert_generated_clean(host))
                host_manifest = _project_manifest(host)
                _collect_failure(failures, lambda: _validate_generated_manifest(host_manifest, "QualityItemHost"))
                main_source = host / "Src" / "Main.bd"
                main_source.write_text("pub i32 Main() { return 0; }\n", encoding="utf-8")
                _collect_failure(failures, lambda: _ensure_manifest_and_lock(host, host_manifest, cli))
                _collect_failure(
                    failures,
                    lambda: _run_cli(cli, ["analyze", "--project", str(host_manifest), "--locked", "--plain"], cwd=host, stage="analysis"),
                )
                target = host / "Src" / f"{value}.bd"
                _generate_item_template(
                    cli,
                    source_rel,
                    host,
                    host_manifest,
                    value,
                )
                if not target.is_file():
                    raise QualityFailure("generation", "generation", f"item template did not emit {target}")
                _collect_failure(failures, lambda: _assert_generated_clean(host))
                if target.name != f"{value}.bd":
                    failures.append(QualityFailure("generation", "generation", f"item output path must be {value}.bd, got {target.name}"))
                _collect_failure(
                    failures,
                    lambda: _run_cli(cli, ["analyze", "--project", str(host_manifest), "--locked", "--plain"], cwd=host, stage="analysis"),
                )
                _raise_collected_failures(failures)
                return

            symbols: dict[str, str] = {}
            primary_name = value
            if member == "project":
                primary_name = None
                symbols = {"name": value, "shortName": "quality-authoring"}
            _new_template(cli, source_rel, output, symbols, primary_name=primary_name)
            # The project template intentionally emits another template source
            # tree whose symbols must remain available to its future users.
            allowed = (".beskid/template.json", "content") if member == "project" else ()
            _collect_failure(failures, lambda: _assert_generated_clean(output, allowed_prefixes=allowed))
            manifest = _project_manifest(output)
            _collect_failure(failures, lambda: _validate_generated_manifest(manifest, value))
            if member == "project":
                print("quality check: project analysis=NOT_APPLICABLE (template authoring package)")
                _raise_collected_failures(failures)
                return
            executable = member in {"console", "host", "fiber_demo"}
            _check_project(cli, output, build=True, run=executable, failures=failures, requested_name=value)
            _raise_collected_failures(failures)

        for member, *_ in TEMPLATE_MEMBERS:
            try:
                _template_result(member, lambda member=member: run_template(member))
            except QualityFailure as failure:
                failures.append(f"{member}:{failure.category}")
        if failures:
            raise QualityFailure("quality", "quality", f"generated template failures: {', '.join(failures)}")
    return failures


def validate_source() -> None:
    if not WORKSPACE_MANIFEST.is_file():
        raise SystemExit(f"Missing workspace manifest: {WORKSPACE_MANIFEST}")
    if not WORKSPACE_PACKAGE_JSON.is_file():
        raise SystemExit(f"Missing workspace publish metadata: {WORKSPACE_PACKAGE_JSON}")

    workspace_text = WORKSPACE_MANIFEST.read_text(encoding="utf-8")
    if _project_field(workspace_text, "name") != "beskid_templates":
        raise SystemExit("beskid_templates.bws name must be beskid_templates")

    workspace_package = json.loads(WORKSPACE_PACKAGE_JSON.read_text(encoding="utf-8"))
    if workspace_package.get("schema") != "beskid.workspace.package.v1":
        raise SystemExit("workspace.package.json schema must be beskid.workspace.package.v1")
    members = workspace_package.get("members")
    if not isinstance(members, dict):
        raise SystemExit("workspace.package.json must declare members")

    for member_id, source_rel, project_name, registry_id in TEMPLATE_MEMBERS:
        member_root = ROOT / source_rel
        manifest = member_root / f"{project_name}.bproj"
        template_json = member_root / ".beskid" / "template.json"
        if not manifest.is_file():
            raise SystemExit(f"Missing member manifest: {manifest}")
        if not template_json.is_file():
            raise SystemExit(f"Missing template manifest: {template_json}")

        proj = manifest.read_text(encoding="utf-8")
        if _project_field(proj, "name") != project_name:
            raise SystemExit(f"{manifest}: project.name must be {project_name!r}")
        root_block = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*\{", proj)
        if root_block is None or root_block.group(1) != project_name:
            raise SystemExit(f"{manifest}: root block must match project.name {project_name!r}")
        if _project_field(proj, "type") != "Template":
            raise SystemExit(f"{manifest}: project.type must be Template")

        meta = members.get(member_id)
        if not isinstance(meta, dict):
            raise SystemExit(f"workspace.package.json missing member {member_id!r}")
        if meta.get("package") != registry_id:
            raise SystemExit(
                f"workspace.package.json[{member_id}].package must be {registry_id!r}, "
                f"got {meta.get('package')!r}"
            )

        _validate_template_manifest(template_json, registry_id)

        for child in member_root.iterdir():
            if child.name == ".beskid" or child.suffix == ".bproj":
                continue
            if child.is_dir():
                _scan_forbidden_corelib_optout(child)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate first-party templates and generated projects")
    parser.add_argument("--cli", default=os.environ.get("BESKID_CLI_BIN"), help="candidate beskid executable (or BESKID_CLI_BIN)")
    parser.add_argument("--static-only", action="store_true", help="run source and metadata checks without instantiating projects")
    parser.add_argument("--verify-invalid-fixture", action="store_true", help="verify the candidate CLI rejects an intentionally invalid .bd file")
    args = parser.parse_args()
    validate_source()
    if args.static_only:
        print(f"quality OK: {len(TEMPLATE_MEMBERS)} template member(s) (static)")
        return 0
    if not args.cli:
        raise SystemExit("BESKID_CLI_BIN or --cli is required for generated-output quality")
    cli = str(Path(args.cli).expanduser().resolve())
    if not Path(cli).is_file() or not os.access(cli, os.X_OK):
        raise SystemExit(f"Candidate Beskid CLI is not executable: {cli}")
    corelib_root = os.environ.get("BESKID_CORELIB_ROOT", "").strip()
    if not corelib_root or not (Path(corelib_root) / "CoreLib.bws").is_file():
        raise SystemExit("BESKID_CORELIB_ROOT is required for generated-output quality")
    print(f"quality CLI: {cli}")
    if args.verify_invalid_fixture:
        try:
            with tempfile.TemporaryDirectory(prefix="beskid-template-quality-fixture-") as temp:
                _verify_invalid_fixture(cli, Path(temp))
        except QualityFailure as failure:
            print(f"quality FAIL [{failure.category}]: {failure}")
            return 1
    try:
        _check_generated_templates(cli)
    except QualityFailure as failure:
        print(f"quality FAIL [{failure.category}]: {failure}")
        return 1
    print(f"quality OK: {len(TEMPLATE_MEMBERS)} generated template member(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
