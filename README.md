# Beskid project templates

First-party [`beskid.template.v1`](https://beskid-lang.org/platform-spec/tooling/project-scaffolding/project-templates/design-model/) packages published under the **`beskid.templates.*`** registry namespace.

Repository: [Cyber-Nomad-Collective/beskid_templates](https://github.com/Cyber-Nomad-Collective/beskid_templates)

## Layout

| Path | Registry id | CLI `shortName` | `tags.type` |
| --- | --- | --- | --- |
| `packages/console` | `beskid.templates.console` | `console` | `project` |
| `packages/lib` | `beskid.templates.lib` | `lib` | `project` |
| `packages/project` | `beskid.templates.project` | `template` | `project` |
| `packages/workspace-demo` | `beskid.templates.workspace-demo` | `workspace-demo` | `workspace` |
| `packages/contract-item` | `beskid.templates.contract-item` | `contract` | `item` |
| `packages/host` | `beskid.templates.host` | `host` | `project` |
| `packages/fiber-demo` | `beskid.templates.fiber-demo` | `fiber-demo` | `project` |

Each member is a **`type: Template`** authoring tree:

- `<project.name>.bproj` — canonical workspace member manifest (`template { shortName, identity }`)
- `.beskid/template.json` — authoritative engine manifest (`beskid.template.v1`)
- `content/` (or `workspace/`, `item/`) — scaffold sources copied on instantiation

Template roots are **not** runnable with `beskid build`; publication packs each member as a separate template artifact, promoting `.beskid/template.json` to the artifact-root `template.json` required by pckg.

## Authoring rules

- Use **`{{symbolId}}`** placeholders only (no alternate delimiter engines).
- Do **not** emit `noCorelib`, `useCorelib: false`, or other corelib opt-out keys in generated `.bproj` files. Host projects resolve **corelib** implicitly when `beskid new` writes `Project.lock` and on every `beskid check`, `build`, or `run`.
- Avoid embedding foreign template engine schemas or .NET-style token syntax in sources.
- Keep `.beskid/template.json` out of generated output unless a source block intentionally copies it for documentation.

Normative contracts: [design model](https://beskid-lang.org/platform-spec/tooling/project-scaffolding/project-templates/design-model/) and [examples](https://beskid-lang.org/platform-spec/tooling/project-scaffolding/project-templates/examples/).

## Local development (CLI)

The Beskid CLI discovers and instantiates these packages from pckg:

```bash
# List available templates
beskid new --list

# Instantiate by short name
beskid new MyGame --template console -o ./MyGame

# Use this repository without publishing
beskid new Demo --path ./packages/console -o ./Demo
```

Registry install (after publish):

```bash
beskid package template install beskid.templates.console
```

## CI and publication

CI is centralized in the superrepo's native `Corelib and templates` workflow. The publisher validates and packs every production corelib and first-party template artifact before the first registry write.

Required secret for publish lanes: `BESKID_PCKG_KEY` (mapped to `BESKID_PCKG_API_KEY`).

From an initialized superrepo checkout, validate the complete publication set without credentials or registry mutation:

```bash
bash scripts/ci/corelib-publish.sh --dry-run
```

## Workspace

`beskid_templates.bws` lists all template members. `workspace.package.json` (`beskid.workspace.package.v1`) is the single metadata source for the seven per-package registry publications.

## License

Beskid-owned templates are licensed under the [Apache License 2.0](LICENSE).
