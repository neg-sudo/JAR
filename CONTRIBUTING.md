# Contributing to JAR

Thanks for helping improve JAR. This guide covers the development workflow,
coding standards and release process.

## Code of conduct

Be respectful and constructive. Harassment or personal attacks are not welcome.
Assume good intent and discuss ideas, not people.

## Getting started

```bash
git clone https://github.com/neg-sudo/JAR.git
cd JAR
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m unittest discover -s tests -t .
```

The core has no third-party runtime dependencies. GUI and OS-trash extras are
optional and should never be required by core modules.

## Project layout

```
jar/            core package and CLI
  gui/          optional desktop app
tests/          stdlib unittest suite
packaging/      PyInstaller specs
scripts/        entry points, icon generator, smoke test, release packager
docs/           configuration and architecture notes
.github/        CI and release workflows
```

## Coding standards

- Target **Python 3.9+**. Avoid syntax and stdlib APIs newer than 3.9.
- The engine and CLI must remain **standard-library only**.
- Use `from __future__ import annotations` in new modules.
- Prefer small, typed functions and dataclasses where they clarify data.
- Keep imports local for optional dependencies (GUI, tray, Send2Trash).
- Never print from library code; use the logger or return values.
- All paths must go through the safety helpers before modification.
- Every new behaviour needs a test in `tests/`.
- Keep user-facing text free of vendor or legacy branding; the product is JAR.

## Tests

```bash
python -m unittest discover -s tests -t .        # everything
python -m unittest tests.test_organizer -v       # one module
python -m unittest tests.test_rules.RuleEngineTests.test_builtin_classification
```

Guidelines:

- Tests must not touch the real home directory. Use `tests.helpers.SandboxTestCase`
  or set `JAR_CONFIG_DIR` / `JAR_DATA_DIR`.
- Test both success and failure paths.
- Avoid timing-sensitive tests where possible; when needed, use generous
  timeouts.
- Tests must pass on Linux, macOS and Windows.

## Manual checks

```bash
python -m compileall -q jar
python scripts/smoke_test.py --source
```

For GUI changes, run `jar doctor` and `jar gui` with the GUI extras installed.

## Commit messages

Use a short imperative subject, optionally with a scope:

```
cli: keep JSON output valid for organize
rules: add screenshot classification example
docs: document conflict strategies
```

Keep commits focused. Update `CHANGELOG.md` for user-visible changes.

## Pull requests

1. Fork the repository and create a topic branch.
2. Add or update tests and documentation.
3. Run the full suite and smoke test.
4. Describe the change, the motivation and any trade-offs.
5. Link related issues.

CI must be green before merging.

## Release process

1. Update `__version__` in `jar/version.py` and `pyproject.toml`.
2. Update `CHANGELOG.md` with the release date.
3. Run the full test suite and smoke test.
4. Commit, then tag and push:

   ```bash
   git tag v2.0.0
   git push origin v2.0.0
   ```

5. `.github/workflows/release.yml` builds every platform, runs the smoke test,
   packages archives with checksums and publishes the GitHub release.
6. Verify the release page contains all artifacts and `SHA256SUMS.txt`.

## Security

Do not commit tokens, credentials or personal paths. Report security issues
privately to the maintainer rather than opening a public issue.
