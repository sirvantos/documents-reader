"""The structure survey reads documents available after reading straight from the database."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from tests.integration.test_read import add_files, set_stage
from tests.synthetic import make_pdfs as mk

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "survey_structure.py"
spec = importlib.util.spec_from_file_location("survey_structure", SCRIPT)
assert spec is not None and spec.loader is not None
survey = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = survey  # @dataclass looks its module up there
spec.loader.exec_module(survey)


def test_surveys_read_documents_only(cli, db, tmp_path):
    ids = add_files(
        cli,
        tmp_path / "in",
        [
            lambda p: mk.make_contract_ru(p, pages=3),
            mk.make_blank_page,
            lambda p: mk.make_contract_ru(p, pages=2),
        ],
    )
    assert cli("read").exit_code == 0
    contract, blank, failed = ids
    set_stage(db, failed, "reading", "failed", "не удалось прочитать")

    docs = survey.load_documents(db)

    # the blank document has no read page, the failed one is not available after reading
    assert [d.doc_id for d in docs] == [contract]
    (s,) = docs
    assert s.pages == 3
    assert s.style == "«N. обычный текст» и «N.M»"
    assert s.level1_plain == 6 and s.level1_caps == 0
    # 1.1 first; 1.2 1.3 2.2 3.2 4.2 next; 2.1 3.1 4.1 5.1 6.1 new section
    assert s.steps["first"] == 1 and s.steps["next"] == 5 and s.steps["new_section"] == 5
    assert s.preamble_share is not None and 0 < s.preamble_share < 0.2
    assert s.tail_share == 0
    assert blank not in {d.doc_id for d in docs}
