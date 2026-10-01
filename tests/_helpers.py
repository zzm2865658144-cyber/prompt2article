"""Shared test helpers.

Scratch directories are created with a plain ``mkdir`` and removed with
``shutil.rmtree`` rather than through :mod:`tempfile`.

That is deliberate: ``tempfile.mkdtemp`` creates its directory with mode
``0o700``. On Windows that path installs a restrictive ACL, and inside a
confined DSH session the resulting directory can no longer be traversed at all
-- writes and even ``listdir`` fail with ``PermissionError``. ``os.mkdir(path)``
without an explicit mode does not trigger it.

Keeping scratch space inside the project also means the tests do not depend on
the OS temp directory being writable, which is not guaranteed in sandboxes and
locked-down CI containers.
"""

from __future__ import annotations

import contextlib
import shutil
import uuid
from pathlib import Path
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRATCH = PROJECT_ROOT / ".tmp-tests"


@contextlib.contextmanager
def temp_dir() -> Iterator[Path]:
    """Yield a fresh scratch directory inside the project, removed on exit."""
    _SCRATCH.mkdir(parents=True, exist_ok=True)
    path = _SCRATCH / f"case-{uuid.uuid4().hex[:8]}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
