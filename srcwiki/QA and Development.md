# QA and Development

#development #qa #testing

## Overview

The project uses a comprehensive QA pipeline with linting, type checking, security scanning, code quality metrics, and testing. Two QA scripts are provided:

| Script | Use Case | Checks |
|--------|----------|--------|
| `./qa_quick.sh` | Daily development | Format, lint, type check, security |
| `./qa_check.sh` | Before pushing | All of above + complexity, dead code, docstrings, tests |

Or use Make:
```bash
make qa-quick   # Quick checks
make qa         # Full QA suite
```

---

## Tool Configuration

All tools are configured in `pyproject.toml`:

### Ruff (Linting & Formatting)

```bash
make format   # Auto-format
make lint     # Check only
```

- **Line length:** 120
- **Target:** Python 3.12
- **Rules enabled:** pycodestyle, pyflakes, isort, pep8-naming, pyupgrade, flake8-bugbear, flake8-comprehensions, flake8-simplify, flake8-use-pathlib
- **Quote style:** double
- **Indent style:** spaces
- **Line ending:** LF

### Pyright (Type Checking)

```bash
make type
```

- **Mode:** basic
- Reports suppressed: `reportMissingImports`, `reportMissingTypeStubs`, `reportOptionalMemberAccess`, `reportOptionalSubscript`, `reportOptionalCall`, `reportAttributeAccessIssue`
- **Scope:** `src/` only (tests excluded)

### Bandit (Security Scanning)

```bash
make security
```

- Scans `src/` for security issues
- Skips `B101` (assert warnings)
- Reports medium severity and above (`-ll`)

### Radon (Code Complexity)

```bash
make complexity
```

Reports:
- **Cyclomatic complexity** — per-function complexity scores (A-F)
- **Maintainability index** — per-file maintainability scores (A-C)

### Vulture (Dead Code Detection)

```bash
make dead-code
```

- Scans `src/` for unused code
- Minimum confidence: 80%

### Interrogate (Docstring Coverage)

```bash
make docstrings
```

- **Fail threshold:** 60% coverage
- Ignores `__init__` methods, magic methods, and nested classes
- Scope: `src/` only

---

## Testing

```bash
make test        # With coverage report
make test-quick  # Without coverage
```

### Configuration

- **Framework:** pytest 8+
- **Test directory:** `tests/`
- **Async mode:** auto (via `pytest-asyncio`)
- **Coverage source:** `src/`
- **Markers:** strict mode (no unknown markers)

### Coverage Settings

- **Source:** `src/`
- **Excluded:** tests, `__pycache__`, venv
- **Excluded lines:** `pragma: no cover`, `__repr__`, `raise NotImplementedError`, `raise AssertionError`, `if TYPE_CHECKING`, `if __name__ == .__main__.:`, `@abstractmethod`

---

## QA Scripts

### `qa_quick.sh` — Quick Checks

Runs 4 checks sequentially with `set -e` (stops on first failure):

1. `ruff format src` — auto-format
2. `ruff check src --fix` — lint with auto-fix
3. `pyright src` — type check (non-blocking)
4. `bandit -r src -ll -q` — security scan (non-blocking)

### `qa_check.sh` — Comprehensive QA

Runs 5 phases, tracking failure count:

| Phase | Checks | Blocking |
|-------|--------|----------|
| 1. Formatting & Linting | Ruff format + lint | Yes |
| 2. Type Checking | Pyright | Yes |
| 3. Security Scanning | Bandit | Yes |
| 4. Code Quality | Radon (info only), Vulture, Interrogate | Partially |
| 5. Testing | Pytest with coverage | Yes |

Exits with non-zero status if any check fails.

---

## Dev Dependencies

Install with:
```bash
pip install -r requirements-dev.txt
# or
make install-dev
```

| Package | Version | Purpose |
|---------|---------|---------|
| `ruff` | >=0.7.0 | Linting and formatting |
| `pyright` | >=1.1.350 | Type checking |
| `bandit` | >=1.7.6 | Security scanning |
| `radon` | >=6.0.1 | Cyclomatic complexity and maintainability |
| `vulture` | >=2.11 | Dead code detection |
| `interrogate` | >=1.5.0 | Docstring coverage |
| `pytest` | >=8.0.0 | Test framework |
| `pytest-cov` | >=4.1.0 | Coverage reporting |
| `pytest-asyncio` | >=0.24.0 | Async test support |

---

## Cleanup

```bash
make clean
```

Removes: `__pycache__`, `.pytest_cache`, `.ruff_cache`, `htmlcov`, `.coverage`

## Related Pages

- [[Setup and Installation]] — Installing dev dependencies
- [[Architecture]] — Code organization
- [[System Design]] — Module structure
