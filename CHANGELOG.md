# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add first-party `host` and `fiber-demo` project template packages and register
  them in the template workspace metadata.

### Changed

- Port the template quality gate and first-party templates to the 0.6 CLI:
  `check` replaces `analyze`, `dev project lock`/`fetch` replace `lock`/`fetch`,
  `beskid new` takes the positional project name, the Corelib aggregate locks as
  `Core`, inline manifest dependency blocks join the Corelib closure, the fiber
  demo imports `Core.Results`/`Concurrency.Fiber`, and type fields use `,`.
- Strengthen generated-output quality checks to reject signal-terminated parser
  runs and verify materialized Corelib sources against the supplied root.
- License all Beskid-owned templates under Apache-2.0.
- Align template quality and publishing scripts with the current workspace
  manifest layout.
- Normalize every template project name and `.bproj` filename to a valid
  canonical Beskid identifier while retaining the public `beskid.templates.*`
  registry identities.
- Publish all seven templates as independently validated `.bpk` artifacts via
  the superrepo's native corelib-and-templates release lane.

### Fixed

- Repair console and workspace app entrypoints to use the current public `Main`
  declaration syntax.
- Generate a runnable host with a default-constructible singleton service and
  preserve registry activation through `launch`.
- Import fibers through the implicit `Std` namespace and verify the joined
  worker result before exiting successfully.

### Removed

- Remove the obsolete `publish_templates.py` skeleton and its duplicate,
  non-functional package inventory; `workspace.package.json` now feeds the
  single native publisher.
