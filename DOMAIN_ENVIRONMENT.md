# Reproduce the data-engineering environment

Source: https://github.com/hynek/structlog/commit/81779f0abe5942018c543e4a7cb047e92d2b5ad8

This repository republishes the tracked files of that upstream commit under their original licenses.
Upstream CI workflows are omitted from the evaluation snapshot. This commit adds environment instructions
and the dependency lock only. The source license is Apache-2.0 OR MIT; original license and attribution files remain.

Python 3.13.15 and uv were used on Linux. From a fresh checkout:

```sh
uv venv --python 3.13.15 .venv
export PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
mkdir -p .venv/tmp
export TMPDIR="$PWD/.venv/tmp"
uv pip install --python .venv/bin/python -r requirements-domain.lock
uv pip install --python .venv/bin/python --no-build-isolation --no-deps -e .
.venv/bin/python -B -c 'import multiprocessing; import pytest; raise SystemExit(pytest.main())' -q -o addopts= -p no:cacheprovider -p pytest_asyncio.plugin tests/test_contextvars.py tests/test_stdlib.py tests/processors
```

The selected tests use small fixtures or in-process substitutes. They need no remote service after dependency setup.
Start a fresh checkout and rebuild its virtual environment to restore initial state.
