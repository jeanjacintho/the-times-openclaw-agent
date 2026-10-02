"""wiki_setup.py: the owner's wiki made ready for the paper."""
from __future__ import annotations

import pytest

from conftest import load_module
from wiki import OVERVIEW, ROOT, SCHEMA, Wiki

ws = load_module("wiki_setup", "pt-shared/scripts/wiki_setup.py")


def wiki_dir(mac):
    return mac.home / "Plow" / "wiki"


def files(mac):
    return {p: p.read_bytes() for p in wiki_dir(mac).rglob("*") if p.is_file()}


class TestEnsure:
    def test_a_mac_without_a_wiki_gets_one_the_paper_can_write(self, mac):
        ws.ensure(Wiki(mac.call_tool), "cht_1")
        toml = (wiki_dir(mac) / "wiki.toml").read_text()
        assert f'[roots."{ROOT}"]\nwriter = "thetimes"' in toml
        assert (wiki_dir(mac) / SCHEMA).exists() and (wiki_dir(mac) / OVERVIEW).exists()
        assert mac.wiki("validate")["exit_code"] == 0

    def test_ready_means_nothing_is_rewritten(self, mac):
        w = Wiki(mac.call_tool)
        ws.ensure(w, "cht_1")
        before = files(mac)
        assert ws.ensure(w, "cht_1") == []
        assert files(mac) == before

    def test_another_agents_root_and_pages_are_left_as_they_were(self, mac):
        mac.wiki("init", "~/Plow/wiki")
        toml = wiki_dir(mac) / "wiki.toml"
        toml.write_text(toml.read_text() + '\n[roots."projects/str"]\nwriter = "str"\n')
        theirs = wiki_dir(mac) / "entities" / "people" / "raj.md"
        theirs.parent.mkdir(parents=True, exist_ok=True)
        theirs.write_text("---\ntitle: Raj\n---\n")
        ws.ensure(Wiki(mac.call_tool), "cht_1")
        assert '[roots."projects/str"]\nwriter = "str"' in toml.read_text()
        assert theirs.read_text() == "---\ntitle: Raj\n---\n"

    def test_the_root_already_declared_in_another_spelling_is_left_alone(self, mac):
        mac.wiki("init", "~/Plow/wiki")
        toml = wiki_dir(mac) / "wiki.toml"
        toml.write_text(toml.read_text() + f"\n[roots.'{ROOT}']\nwriter = \"thetimes\"\n")
        before = toml.read_bytes()
        ws.ensure(Wiki(mac.call_tool), "cht_1")
        assert toml.read_bytes() == before
        assert mac.wiki("validate")["exit_code"] == 0

    def test_the_paper_writes_under_its_own_name(self):
        assert ROOT == "projects/thetimes"
        assert OVERVIEW == f"{ROOT}/thetimes.md"


class TestCli:
    def test_an_unreachable_mac_is_an_error_not_ready(self, mac, monkeypatch):
        mac.asleep = True
        monkeypatch.setattr(ws, "connect", lambda: Wiki(mac.call_tool))
        monkeypatch.setenv("PLOW_HOME_CHANNEL", "cht_1")
        with pytest.raises(SystemExit) as exc:
            ws.main([])
        assert str(exc.value).startswith("error: wiki not ready — Mac unreachable")
