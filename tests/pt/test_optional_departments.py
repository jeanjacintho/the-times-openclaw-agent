"""Department choices must survive setup and constrain the real page output."""
import json
import re

import pytest

from conftest import load_module

settings = load_module("set_desks", "pt-shared/scripts/set_desks.py")
render = load_module("render_edition", "pt-edition/scripts/render_edition.py")
finalize = load_module("finalize_setup", "pt-setup/scripts/finalize_setup.py")

READY = {"owner": {"timezone": "UTC"}, "delivery": {"hour": "07:00"},
         "printer": {"configured": False}}


@pytest.mark.parametrize("desk", ["weather", "calendar", "mail"])
def test_department_can_be_enabled_and_disabled_without_losing_preferences(tmp_path, monkeypatch, desk):
    monkeypatch.setenv("PT_HOME", str(tmp_path))
    path = tmp_path / "config.json"
    path.write_text(json.dumps(READY))
    assert settings.main([desk, "on"]) == 0
    assert json.loads(path.read_text()) == {**READY, desk: {"configured": True}}
    assert settings.main([desk, "off"]) == 0
    assert json.loads(path.read_text())[desk] == {"configured": False}


def test_invalid_change_does_not_overwrite_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_HOME", str(tmp_path))
    path = tmp_path / "config.json"
    path.write_text('{"owner": {"timezone": ""}}')
    before = path.read_bytes()
    assert settings.main(["weather", "on"]) == 1
    assert path.read_bytes() == before


def test_setup_choices_survive_finalization_and_absent_choices_stay_off(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_HOME", str(tmp_path))
    path = tmp_path / "config.json"
    draft = {"local_hour": "07:00", "printer": {"configured": False},
             "mail": {"configured": True}, "news_asked": True}
    path.with_name(".setup-draft.json").write_text(json.dumps(draft))
    recorder = load_module("record_setup", "pt-shared/scripts/record_setup.py")
    assert recorder.main(["record_setup.py", str(path), "calendar.configured=true"]) == 0
    assert not path.exists()
    assert finalize.main(["finalize_setup.py", str(path), "--owner-tz", "UTC"]) == 0
    config = json.loads(path.read_text())
    assert config["calendar"]["configured"] is True
    assert config["weather"]["configured"] is False
    assert config["mail"]["configured"] is True


@pytest.mark.parametrize("enabled,switches_present", [
    (None, True), (None, False),
    ("weather", True), ("calendar", True), ("mail", True), ("sports", True),
])
def test_only_chosen_departments_reach_html_and_chat(tmp_path, enabled, switches_present):
    desks = ("weather", "calendar", "mail", "sports")
    edition = {"date": "2026-10-07", "sections": [
        {"kind": "section", "desk": desk, "title": desk, "body": f"Content for {desk}"}
        for desk in desks
    ] + [{"kind": "section", "desk": "news", "topic_id": "t_abcd", "title": "News", "body": "Chosen news"}]}
    source = tmp_path / "edition.json"
    source.write_text(json.dumps(edition))
    config = tmp_path / "config.json"
    config.write_text(json.dumps({**READY, **({desk: {"configured": desk == enabled}
                                             for desk in desks} if switches_present else {})}))
    page, chat = tmp_path / "page.html", tmp_path / "chat.txt"
    assert render.main([str(source), "--config", str(config), "--html", str(page), "--chat", str(chat)]) == 0
    assert "Chosen news" in re.sub(r"<[^>]+>", "", page.read_text())
    for desk in desks:
        assert (f"Content for {desk}" in chat.read_text()) == (desk == enabled)
        # Weather without a forecast is a named miss in the masthead, not body prose.
        if desk not in ("weather", "mail"):
            assert (f"Content for {desk}" in page.read_text()) == (desk == enabled)


def test_disabled_stale_scratch_cannot_block_a_selected_department(tmp_path):
    run = tmp_path / "run"
    (run / "desk-weather").mkdir(parents=True)
    (run / "desk-weather" / "notes.json").write_text('{"date":"2000-01-01"}')
    out = run / "paper"
    out.mkdir()
    source = out / "edition.json"
    source.write_text(json.dumps({"date": "2026-10-07", "sections": [
        {"kind": "section", "desk": "calendar", "title": "Agenda", "body": "Agenda today"}]}))
    config = tmp_path / "config.json"
    config.write_text('{"calendar":{"configured":true}}')
    assert render.main([str(source), "--config", str(config), "--html", str(out / "page.html")]) == 0
    assert "Agenda today" in (out / "page.html").read_text()


@pytest.mark.parametrize("desk", ["weather", "calendar"])
def test_invalid_optional_switch_is_refused(desk):
    import pt_config_gate
    assert f"{desk}.configured" in pt_config_gate.gate({**READY, desk: {"configured": "yes"}})



def test_corrupt_config_cannot_disclose_mail(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("broken JSON")
    source = tmp_path / "edition.json"
    source.write_text(json.dumps({"date": "2026-10-07", "sections": [
        {"kind": "section", "desk": "mail", "title": "Mail", "body": "Private message"}]}))
    page = tmp_path / "page.html"
    with pytest.raises(SystemExit, match="config"):
        render.main([str(source), "--config", str(config), "--html", str(page)])
    assert not page.exists()


