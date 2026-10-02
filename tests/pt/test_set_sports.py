"""set_sports.py -- the owner follows or drops a team after setup."""
from __future__ import annotations

import contextlib
import io
import json

import pytest

from conftest import load_module

sports = load_module("set_sports", "pt-shared/scripts/set_sports.py")

READY = {
    "owner": {"timezone": "America/Sao_Paulo", "language": "Portuguese"},
    "delivery": {"hour": "07:00", "lead_minutes": 60},
    "printer": {"configured": False, "name": None},
    "mail": {"configured": True},
}


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_HOME", str(tmp_path))
    path = tmp_path / "config.json"
    path.write_text(json.dumps(READY))
    return path


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = sports.main(list(argv))
    return code, out.getvalue().strip(), err.getvalue().strip()


def test_the_first_team_turns_the_desk_on(config):
    assert run("add", "Flamengo", "bra.1") == (0, "SPORTS:Flamengo (bra.1)", "")
    written = json.loads(config.read_text())
    assert written["sports"] == {"configured": True, "followed": [{"team": "Flamengo", "league": "bra.1"}]}
    assert {k: v for k, v in written.items() if k != "sports"} == READY


def test_teams_accumulate_and_list_reads_them_back(config):
    run("add", "Flamengo", "bra.1")
    run("add", "Lakers", "nba")
    assert run("list") == (0, "SPORTS:Flamengo (bra.1), Lakers (nba)", "")


def test_adding_a_followed_team_again_only_updates_its_league(config):
    run("add", "Flamengo", "bra.1")
    assert run("add", "flamengo", "bra.copa")[1] == "SPORTS:Flamengo (bra.copa)"


def test_removing_the_last_team_turns_the_desk_off(config):
    run("add", "Flamengo", "bra.1")
    assert run("remove", "FLAMENGO") == (0, "SPORTS:none", "")
    assert json.loads(config.read_text())["sports"] == {"configured": False, "followed": []}


def test_removing_a_team_that_is_not_followed_changes_nothing(config):
    run("add", "Flamengo", "bra.1")
    before = config.read_text()
    code, out, err = run("remove", "Lakers")
    assert code == 1 and out == "" and "not followed" in err
    assert config.read_text() == before


def test_the_cap_is_enforced(config):
    for n in range(5):
        run("add", f"Team {n}", "nba")
    before = config.read_text()
    code, _, err = run("add", "One too many", "nba")
    assert code == 1 and "at most 5" in err
    assert config.read_text() == before


@pytest.mark.parametrize("argv", [(), ("follow", "x"), ("add", "Flamengo"), ("add", " ", "nba"),
                                  ("remove",), ("list", "extra")])
def test_bad_arguments_change_nothing(config, argv):
    code, out, err = run(*argv)
    assert code == 1 and out == "" and err.startswith("error:")
    assert json.loads(config.read_text()) == READY


def test_missing_config_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_HOME", str(tmp_path))
    code, _, err = run("add", "Flamengo", "bra.1")
    assert code == 1 and "finish setup first" in err


def test_a_config_the_gate_refuses_is_not_overwritten(config):
    config.write_text(json.dumps({**READY, "sports": {"configured": "yes", "followed": []}}))
    before = config.read_text()
    code, _, err = run("add", "Flamengo", "bra.1")
    assert code == 0  # the script rewrites the whole block, so a corrupt one is repaired
    assert json.loads(config.read_text())["sports"]["configured"] is True
    assert before != config.read_text() and err == ""
