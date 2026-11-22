"""The guard that keeps models off machines where they must not run (CLAUDE.md «Machines»).

`DOCREADER_FORBID_MODELS` is set on the development server, in `compose.yaml` and by the
test fixtures (except the `real_model` group). The recognition engine (feature 13) and
the language model (feature 05) both refuse to start while it is set.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

FORBID_MODELS_ENV = "DOCREADER_FORBID_MODELS"


def models_forbidden(env: Mapping[str, str] = os.environ) -> bool:
    """True when DOCREADER_FORBID_MODELS is set to anything but blanks."""
    return bool(env.get(FORBID_MODELS_ENV, "").strip())
