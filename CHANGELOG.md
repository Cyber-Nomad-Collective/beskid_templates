# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add first-party `host` and `fiber-demo` project template packages and register
  them in the template workspace metadata.

### Changed

- Align template quality and publishing scripts with the current workspace
  manifest layout.
- Normalize every template project name and `.bproj` filename to a valid
  canonical Beskid identifier while retaining the public `beskid.templates.*`
  registry identities.
- Publish all seven templates as independently validated `.bpk` artifacts via
  the superrepo's native corelib-and-templates release lane.

### Removed

- Remove the obsolete `publish_templates.py` skeleton and its duplicate,
  non-functional package inventory; `workspace.package.json` now feeds the
  single native publisher.
