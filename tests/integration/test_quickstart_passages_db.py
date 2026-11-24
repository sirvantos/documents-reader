"""`collect` of scripts/quickstart_passages.py on a synthetic database (feature 07, T023).

Two synthetic contracts are added, read, parsed and indexed with `HashEmbedder`; the
report must show full coverage and traceability and print no contract text. Written by
the main session.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from functools import partial
from pathlib import Path

from tests.fakes.embedding import HashEmbedder
from tests.integration.test_read import add_files
from tests.synthetic import make_pdfs as mk

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "quickstart_passages", ROOT / "scripts" / "quickstart_passages.py"
)
assert _spec is not None and _spec.loader is not None
qs = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = qs
_spec.loader.exec_module(qs)


def test_collect_on_indexed_synthetic_contracts(cli, db, tmp_path, use_embedder) -> None:
    makers = [mk.make_passage_contract, partial(mk.make_extraction_contract, variant="base")]
    add_files(cli, tmp_path / "in", makers)
    assert cli("read").exit_code == 0
    assert cli("parse").exit_code == 0
    use_embedder(HashEmbedder())
    result = cli("index", "--json")
    assert result.exit_code == 0, result.stderr
    index_report = json.loads(result.stdout)

    report = qs.collect(db)
    total = index_report["totals"]["passages"]
    assert report.passages == total == report.word_entries == report.vectors
    assert report.states["done"] == 2
    assert (report.uncovered_chars, report.doubled_chars, report.coverage_docs) == (0, 0, [])
    assert report.traceable == total
    assert report.parts["preamble"] == 2 and report.parts["tail"] == 2

    text = "\n".join(qs.render(report))
    for page in mk._PASSAGE_PAGES:  # the synthetic lines must not be printed
        for line in page:
            if len(line) > 8:
                assert line not in text, line
