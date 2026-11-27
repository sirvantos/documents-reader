"""Guard sweep: no `eval` command prints contract content (feature 02, T038, FR-026, FR-006).

One synthetic database with every kind of eval data; every command of contracts/cli.md
runs in its plain and `--json` form, and each output is checked with
`tests.eval_guard.assert_no_values`. The review page assets are checked for external
references.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.eval_guard import assert_no_values, synthetic_secrets
from tests.integration.test_eval_review import cards_of, setup  # noqa: F401 — the fixture

SYNTH = Path(__file__).resolve().parents[1] / "synthetic"


def test_every_eval_command(cli, db, data_dir, setup) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    d1, _ = setup
    outputs: list[str] = []

    def run(*args: object, code: int = 0) -> str:
        for extra in ((), ("--json",)):
            result = cli("eval", *args, *extra)
            assert result.exit_code == code, (args, result.stderr)
            outputs.append(result.stdout + result.stderr)
        return result.stdout

    run("template", "--fields", "prototype")
    built = json.loads(run("review"))
    folder = (data_dir / built["path"]).parent
    answers = {
        "format": "docreader-gold-review/1", "build": built["build"],
        "cards": [{"key": f"{d1}/contract_number", "answer": "agree"},
                  {"key": f"{d1}/amount_without_vat", "answer": "typed",
                   "value": "1 200 000,00"}],
    }
    path = data_dir / "eval" / "answers.json"
    path.write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")
    run("load", path)
    run("fields")
    run("fields", "--source", "rules")
    pick = json.loads(run("blind", "pick"))
    blind = data_dir / pick["template"]
    run("blind", "load", blind)
    run("results")
    record = json.loads(cli("eval", "results", "--json").stdout)["records"][0]["id"]
    run("show", record)
    run("compare", record, record)
    run("export")
    run("questions", "load", SYNTH / "answer_questions.toml")
    run("questions", "generate")

    shown = [
        s[k] for c in cards_of(folder).values()
        for s in ([c["model"]] if c["model"] else []) + c["rules"]
        for k in ("value", "quote")
    ]
    secrets = synthetic_secrets(db, extra=shown)
    for out in outputs:
        assert_no_values(out, secrets)


def test_review_page_assets_are_local(cli, data_dir, setup) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    built = json.loads(cli("eval", "review", "--json").stdout)
    folder = (data_dir / built["path"]).parent
    for asset in folder.iterdir():
        if asset.suffix in (".html", ".json"):
            text = asset.read_text(encoding="utf-8")
            assert not re.search(r"https?:|//[\w.-]+\.\w+/|@import|<link", text), asset.name
        else:
            assert asset.suffix == ".png", asset.name
