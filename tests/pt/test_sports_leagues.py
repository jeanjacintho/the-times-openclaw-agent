"""League preference validation and large-scoreboard layouts."""
import pytest
from conftest import load_module

render = load_module("render_edition", "pt-edition/scripts/render_edition.py")
READY = {"owner": {"timezone": "UTC"}, "delivery": {"hour": "07:00"},
         "printer": {"configured": False}}


@pytest.mark.parametrize("leagues", ["nfl", [{"name": "NFL"}],
                                    [{"name": "NFL", "league": "nfl"}, {"name": "Duplicate", "league": "NFL"}]])
def test_invalid_league_preferences_are_refused(leagues):
    import pt_config_gate
    assert "sports.leagues" in pt_config_gate.gate({**READY, "sports": {
        "configured": True, "followed": [], "leagues": leagues}})



@pytest.mark.parametrize("with_news", [True, False], ids=["news-and-sports", "sports-only"])
def test_large_scoreboard_layout(with_news):
    games = [{"home": f"Home {n}", "away": f"Away {n}", "status": "final",
              "home_score": 21, "away_score": 17} for n in range(16)]
    sections = [{"kind": "section", "desk": "sports", "title": "NFL",
                 "body": "All games", "games": games}]
    if with_news:
        sections.insert(0, {"kind": "section", "desk": "news", "title": "News", "body": "Chosen news"})
    page = render.render_html({"date": "2026-10-07", "sections": sections},
                              "THE TIMES", render.TEMPLATE.read_text())
    assert 'class="side-rail"' not in page
    assert ('class="page-body' in page) == with_news
    assert page.count('class="sp-game"') == 16
    assert "Home 15" in page and "Away 15" in page
