"""The conftest guard sets DOCREADER_FORBID_MODELS for ordinary tests (research R-4)."""

from __future__ import annotations

import os

from tests.conftest import FORBID_MODELS_ENV


def test_ordinary_test_runs_with_models_forbidden() -> None:
    assert os.environ.get(FORBID_MODELS_ENV) == "1"
