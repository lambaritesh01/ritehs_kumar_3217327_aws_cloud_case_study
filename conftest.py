"""Pytest path shim so tests can import the app and Lambda sources directly.

Adds ``app/`` and ``lambda_src/`` to sys.path. No AWS calls; import-safe.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
for _sub in ("app", "lambda_src"):
    _path = os.path.join(_ROOT, _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)
