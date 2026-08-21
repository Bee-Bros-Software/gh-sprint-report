# Contributing

## Setup

```bash
pip install -e ".[dev,docs]"
```

## Before opening a pull request

```bash
pytest --cov=sprint_report --cov-report=term-missing
ruff check src tests
mypy
interrogate -c pyproject.toml src/     # 95% floor, enforced in CI
make -C docs html                      # warnings are errors
```

## House style

- **Google-style docstrings** on every public module, class, function, and
  method, with parameter types, return values, exceptions, and a usage
  example. Docstring coverage is enforced at 95%.
- **PEP 484 type hints** on every signature.
- **Tests for every behaviour**, including the failure paths. Network calls
  are stubbed; the suite must never touch the network.
- Comments explain *why*, not *what*. If a line needs a comment to say what it
  does, rewrite the line.

## Releasing

Tag and push:

```bash
git tag v1.1.0
git push origin v1.1.0
```

`release.yml` builds a binary on each target OS, runs a smoke test that
generates a real deck and workbook, and publishes everything to a GitHub
Release with checksums.
