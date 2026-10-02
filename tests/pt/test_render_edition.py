"""render_edition.py -- the fixed layout, the escape discipline, the gate."""
from __future__ import annotations

import json
import sys
import types

import pytest

from conftest import ROOT, load_module

render = load_module("render_edition", "pt-edition/scripts/render_edition.py")






EVENT = {"time": "10:00", "title": "Customer call: Dana", "note": "Go in with: what they use today"}






def edition_with_weather():
    return edition(sections=[
        {"kind": "section", "title": "Weather", "desk": "weather", "body": "rain", "sources": []},
    ])


def edition(**overrides):
    base = {
        "date": "2026-09-11",
        "sections": [
            {
                "kind": "section",
                "topic_id": "t_8c1d",
                "title": "Weather in Sao Paulo",
                "body": "Rain in the afternoon.",
                "sources": ["https://example.com/weather"],
            }
        ],
    }
    base.update(overrides)
    return base


def write(tmp_path, data):
    path = tmp_path / "edition.json"
    path.write_text(json.dumps(data))
    return path




class TestValidate:












    def test_valid_is_silent(self):
        assert render.validate(edition()) == ""

    def test_missing_date(self):
        assert "date" in render.validate(edition(date="nope"))

    def test_impossible_date(self):
        assert "real calendar" in render.validate(edition(date="2026-02-30"))

    def test_sections_must_be_a_list(self):
        assert "sections is not a list" in render.validate(edition(sections={}))

    def test_unknown_kind(self):
        bad = edition(sections=[{"kind": "news", "title": "x", "body": "y"}])
        assert "kind" in render.validate(bad)

    def test_blank_title(self):
        bad = edition(sections=[{"kind": "section", "title": "", "body": "y"}])
        assert "title is blank" in render.validate(bad)

    def test_assignment_needs_run_on(self):
        bad = edition(sections=[{"kind": "assignment", "title": "x", "body": "y"}])
        assert "run_on is required" in render.validate(bad)

    @pytest.mark.parametrize("section", [
        {"kind": "section", "desk": "news", "title": "x", "body": "y"},
        {"kind": "assignment", "run_on": "2026-09-21", "title": "x", "body": "y"},
    ])
    def test_carried_news_requires_topic_id(self, section):
        assert "topic_id is required" in render.validate(edition(sections=[section]))

    def test_sources_must_be_strings(self):
        bad = edition(sections=[{"kind": "section", "title": "x", "body": "y",
                                 "sources": [1, 2]}])
        assert "sources" in render.validate(bad)

    def test_layout_must_be_main_or_sidebar(self):
        bad = edition(sections=[{
            "kind": "section", "title": "x", "body": "y", "layout": "top",
        }])
        assert "layout is not main|sidebar" in render.validate(bad)

    @pytest.mark.parametrize("desk", ["gossip", ""])
    def test_desk_must_be_known(self, desk):
        # An empty string (unlike None/absent) never reaches fill_news_desk's
        # default -- it must still fail the gate here, not get silently
        # promoted to news.
        bad = edition(sections=[{
            "kind": "section", "title": "x", "body": "y", "desk": desk,
        }])
        assert "desk" in render.validate(bad)

    def test_desk_optional(self):
        assert render.validate(edition()) == ""

    def test_more_than_three_news_articles_is_refused(self):
        stories = [{
            "kind": "section", "title": f"Story {i}", "desk": "news",
            "body": f"Body {i}.", "sources": [],
        } for i in range(4)]
        assert "edition has more than 3 news articles" in render.validate(
            edition(sections=stories)
        )
        assert render.validate(edition(sections=[{
            "kind": "section", "title": "x", "body": "y", "desk": "weather",
        }])) == ""

    def test_location_must_be_a_string_when_present(self):
        bad = edition(location=12)
        assert "location is not a string" in render.validate(bad)

    def test_layout_optional(self):
        assert render.validate(edition()) == ""
        assert render.validate(edition(sections=[{
            "kind": "section", "topic_id": "t_8c1d", "title": "x", "body": "y", "layout": "sidebar",
        }])) == ""

    def test_headline_must_be_a_string_when_present(self):
        bad = edition(sections=[{
            "kind": "section", "title": "x", "body": "y", "headline": 5,
        }])
        assert "headline is not a string" in render.validate(bad)

    def test_headline_optional(self):
        assert render.validate(edition()) == ""

    def test_topic_id_shape(self):
        bad = edition(sections=[{"kind": "section", "title": "x", "body": "y",
                                 "topic_id": "nope"}])
        assert "topic_id" in render.validate(bad)

    def test_forecast_only_on_weather(self):
        bad = edition(sections=[{
            "kind": "section", "title": "Diary", "desk": "calendar", "body": "c",
            "forecast": [{"day": "Tue", "date": "17/05", "icon": "sun", "high": 19, "low": 9}],
        }])
        assert "forecast is only valid on the weather desk" in render.validate(bad)

    def test_forecast_must_be_today_only(self):
        day = {"day": "Tue", "date": "17/05", "icon": "sun", "high": 19, "low": 9}
        empty = edition(sections=[{
            "kind": "section", "title": "Weather", "desk": "weather", "body": "w",
            "forecast": [],
        }])
        week = edition(sections=[{
            "kind": "section", "title": "Weather", "desk": "weather", "body": "w",
            "forecast": [day, {**day, "day": "Wed"}],
        }])
        assert "forecast must contain today's forecast" in render.validate(empty)
        assert "forecast must contain today's forecast" in render.validate(week)

    def test_schedule_only_on_calendar(self):
        bad = edition(sections=[{
            "kind": "section", "title": "Weather", "desk": "weather", "body": "w",
            "schedule": [{"time": "9am", "title": "Sync", "icon": "meeting"}],
        }])
        assert "schedule is only valid on the calendar desk" in render.validate(bad)

    def test_messages_only_on_mail(self):
        bad = edition(sections=[{
            "kind": "section", "title": "Weather", "desk": "weather", "body": "w",
            "messages": [{"sender": "Ana", "subject": "Hi"}],
        }])
        assert "messages is only valid on the mail desk" in render.validate(bad)

    def test_schedule_icon_must_be_known(self):
        bad = edition(sections=[{
            "kind": "section", "title": "Diary", "desk": "calendar", "body": "c",
            "schedule": [{"time": "9am", "title": "Sync", "icon": "party"}],
        }])
        assert "icon is not one of" in render.validate(bad)

    def test_valid_strips_are_silent(self):
        assert render.validate(edition(sections=[
            {"kind": "section", "title": "Weather", "desk": "weather", "body": "w",
             "forecast": [{"day": "Tue", "date": "17/05", "icon": "rain", "high": 17, "low": 6}]},
            {"kind": "section", "title": "Diary", "desk": "calendar", "body": "c",
             "schedule": [{"time": "9am", "title": "Sync", "icon": "meeting"}]},
            {"kind": "section", "title": "Letters", "desk": "mail", "body": "m",
             "messages": [{"sender": "Ana", "subject": "Hi"}]},
        ])) == ""




    def test_news_tag_renders_as_a_kicker_above_the_headline(self):
        html = render.render_html(edition(sections=[{
            "kind": "section", "title": "Markets rally", "desk": "news",
            "tag": "Economia", "body": "Stocks rose.",
            "sources": [],
        }]), render.DEFAULT_MASTHEAD, "{{LEAD}}")
        assert '<p class="kicker">Economia</p>' in html
        assert html.index("kicker") < html.index("Markets rally")
        assert '<span class="tag">Economia</span>' not in html

    def test_lead_body_paginates_as_ordinary_paragraphs(self):
        html = render.render_html(edition(sections=[{
            "kind": "section", "title": "Lead", "desk": "news",
            "body": "One.\n\nTwo.\n\nThree.\n\nFour.",
            "sources": [],
        }]), render.DEFAULT_MASTHEAD, "{{LEAD}}")
        # A 3-cell lead-body table had to stay whole (WeasyPrint paints
        # a split cell in the wrong column), so the body jumped to page
        # 2 while the front still had room. The lead fills leftover
        # space as normal paragraphs.
        assert '<div class="lead-body">' not in html
        assert "dropcap" in html
        assert "<p>" in html

    def test_three_news_articles_render_as_one_lead_above_a_pair(self):
        sections = [{
            "kind": "section", "title": f"Story {i}", "desk": "news",
            "body": f"Body {i}.", "sources": [],
        } for i in range(3)]
        html = render.render_html(edition(sections=sections),
                                  render.DEFAULT_MASTHEAD,
                                  "<main>{{LEAD}}</main>{{NEWS_PAIR}}")
        lead, pair = html.split("</main>", 1)
        assert "Story 0" in lead
        assert "Story 1" not in lead and "Story 2" not in lead
        assert '<div class="news-pair">' in pair
        assert pair.count('<div class="news-pair-cell">') == 2
        assert pair.count("Story 1") == 1 and pair.count("Story 2") == 1

    def test_calendar_rail_is_the_only_printed_event_owner(self):
        html = render.render_html(edition(sections=[
            {"kind": "section", "title": "Agenda", "desk": "calendar",
             "headline": "One call", "body": "10:00 Customer call: Dana",
             "schedule": [{"time": "10:00", "title": "Customer call: Dana",
                            "icon": "call"}], "sources": ["Calendar.app"]},
        ]), render.DEFAULT_MASTHEAD,
            "<aside class=\"calendar-rail\">{{CALENDAR_RAIL}}</aside>")
        assert html.count("Customer call: Dana") == 1
        assert "<h3>TODAY</h3>" not in html
        assert html.count('class="calendar-rail"') == 1
        assert html.count("section--calendar") == 1



      




class TestMasthead:
    def test_json_cannot_name_the_paper(self):
        data = edition(masthead="The Fake Times")
        assert "The Fake Times" not in render.render_chat(data, render.masthead())
        assert render.DEFAULT_MASTHEAD in render.render_chat(data, render.masthead())

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("PT_MASTHEAD", "The Daily Plow")
        assert render.masthead() == "The Daily Plow"

    def test_blank_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("PT_MASTHEAD", "   ")
        assert render.masthead() == render.DEFAULT_MASTHEAD

    def test_printed_page_carries_the_tagline(self):
        template = (ROOT / "pt-edition" / "template.html").read_text()
        page = render.render_html(edition(), render.DEFAULT_MASTHEAD, template)
        assert render.DEFAULT_MASTHEAD in page
        assert "your personal newspaper" in page

class TestChat:
    def test_header_and_section(self):
        text = render.render_chat(edition(), render.DEFAULT_MASTHEAD)
        assert text.startswith("THE TIMES \u2014 Sep 11, 2026")
        assert "\u25b8 Weather in Sao Paulo" in text
        assert "Sources: https://example.com/weather" in text

    @pytest.mark.parametrize("desk", render.DESKS)
    def test_every_desk_prints_gaps_and_sources(self, desk):
        data = edition(sections=[{
            "kind": "assignment", "topic_id": "t_3f2a", "run_on": "2026-09-11", "desk": desk,
            "title": "iPhone 15 price", "body": " ",
            "sources": ["https://shop.example/x"],
            "tag": "special for this edition",
            "could_not_source": ["the Pro model's price"],
        }])
        text = render.render_chat(data, render.DEFAULT_MASTHEAD)
        page = render.render_html(data, render.DEFAULT_MASTHEAD,
                                  "{{LEAD}}{{WEATHER_EAR}}{{DESKS_INLINE}}")
        assert "special for this edition" in text
        assert "Sources:" in text
        assert "Couldn't source: the Pro model" in text
        if desk == "weather":
            assert "Sources:" not in page
            assert "Couldn't source<br>" in page
            assert "the Pro model&#x27;s price" in page
        else:
            assert "Sources:" in page
            assert "Couldn't source: the Pro model" in page
        if desk == "weather":
            assert "(nothing to report this time)" in text
        else:
            assert "(nothing to report this time)" in page
        assert "budget" not in text and "budget" not in page

    def test_empty_budget_is_still_an_edition(self):
        text = render.render_chat(edition(sections=[]), render.DEFAULT_MASTHEAD)
        assert "Nothing to report this time." in text

    def test_sources_deduped(self):
        data = edition(sections=[{
            "kind": "section", "title": "x", "body": "y",
            "sources": ["https://a", "https://a", "https://b"],
        }])
        text = render.render_chat(data, render.DEFAULT_MASTHEAD)
        assert text.count("https://a") == 1

    def test_headline_renders(self):
        # Regression: headline was documented in the SKILL.md example and
        # promised by SOUL.md ("a headline, a short synthesis, and a Sources
        # line") but silently dropped by the renderer -- the model wrote it,
        # nobody ever saw it.
        data = edition(sections=[{
            "kind": "section", "title": "x", "headline": "The real headline",
            "body": "y", "sources": [],
        }])
        text = render.render_chat(data, render.DEFAULT_MASTHEAD)
        assert "The real headline" in text

    def test_missing_headline_is_fine(self):
        text = render.render_chat(edition(), render.DEFAULT_MASTHEAD)
        assert "▸ Weather in Sao Paulo\n  Rain in the afternoon." in text


class TestHtml:
    def test_web_strings_are_escaped(self):
        data = edition(sections=[{
            "kind": "section", "title": "<script>alert(1)</script>",
            "body": "<img onerror=alert(1)>", "sources": ['"><script>'],
        }])
        page = render.render_html(data, render.DEFAULT_MASTHEAD, "<p>{{LEAD}}</p>")
        assert "<script>" not in page
        assert "<img" not in page
        assert "&lt;script&gt;" in page

    def test_placeholders_substituted(self):
        page = render.render_html(edition(), "The Daily", "{{MASTHEAD}}|{{DATE}}|{{LEAD}}")
        assert page.startswith("The Daily|Sep 11, 2026|")
        assert "Weather in Sao Paulo" in page

    def test_headline_renders_escaped(self):
        data = edition(sections=[{
            "kind": "section", "title": "x", "headline": "<b>headline</b>",
            "body": "y", "sources": [],
        }])
        page = render.render_html(data, render.DEFAULT_MASTHEAD, "<p>{{LEAD}}</p>")
        assert 'class="headline"' in page
        assert "<b>headline</b>" not in page
        assert "&lt;b&gt;headline&lt;/b&gt;" in page

    def test_news_stays_in_the_news_slot(self):
        data = edition(sections=[
            {"kind": "section", "title": "News", "body": "y", "sources": []},
            {"kind": "section", "title": "Weather", "layout": "sidebar", "body": "z",
             "sources": []},
        ])
        page = render.render_html(data, render.DEFAULT_MASTHEAD,
                                  "{{LEAD}}{{SECTIONS}}|{{DESKS_INLINE}}")
        main_html, desks = page.split("|", 1)
        assert "News" in main_html and "Weather" in main_html
        assert desks == ""

    def test_no_desks_collapses_the_row(self):
        page = render.render_html(edition(), render.DEFAULT_MASTHEAD, "{{DESKS_INLINE}}")
        assert page == ""

    def test_weather_desk_draws_the_masthead_ear(self):
        data = edition(sections=[
            {"kind": "section", "title": "Dollar", "desk": "news", "body": "up",
             "sources": []},
            {"kind": "section", "title": "Weather", "desk": "weather", "body": "rain",
             "forecast": [{"day": "Tue", "date": "17/05", "icon": "rain", "high": 17, "low": 6}],
             "sources": []},
        ])
        page = render.render_html(data, render.DEFAULT_MASTHEAD,
                                  "{{LEAD}}|{{WEATHER_EAR}}|{{DESKS_INLINE}}")
        main_html, ear, desks = page.split("|", 2)
        assert "Dollar" in main_html and "Weather" not in main_html
        assert "ear-weather" in ear and "wx-icon" in ear
        assert "Dollar" not in ear
        assert desks == ""

    def test_each_desk_is_a_separate_field(self):
        data = edition(sections=[
            {"kind": "section", "title": "News", "desk": "news", "body": "n",
             "sources": []},
            {"kind": "section", "title": "Mail", "desk": "mail", "body": "m",
             "sources": []},
            {"kind": "section", "title": "Weather", "desk": "weather", "body": "w",
             "sources": []},
            {"kind": "section", "title": "Diary", "desk": "calendar", "body": "c",
             "sources": []},
        ])
        page = render.render_html(data, render.DEFAULT_MASTHEAD,
                                  "{{LEAD}}|{{WEATHER_EAR}}|{{DESKS_INLINE}}")
        main_html, ear, desks = page.split("|", 2)
        assert "News" in main_html
        assert "Diary" in desks and "Mail" in desks
        assert "News" not in desks
        assert "section--calendar" in desks and "section--mail" in desks
        assert "section--weather" not in desks
        assert "ear-box" in ear

    def test_weather_forecast_draws_the_ear(self):
        data = edition(sections=[{
            "kind": "section", "title": "Weather", "desk": "weather", "body": "rain",
            "forecast": [{"day": "Tue", "date": "17/05", "icon": "rain", "high": 17, "low": 6}],
            "sources": ["https://example.com/weather"], "could_not_source": ["the rain chance"],
        }])
        page = render.render_html(data, render.DEFAULT_MASTHEAD, "{{WEATHER_EAR}}")
        assert "ear-weather" in page
        assert 'class="wx-icon"' in page
        assert "wx-grid" not in page
        assert "17" in page and "6" in page
        assert "<img" not in page
        assert "Sources:" not in page
        chat = render.render_chat(data, render.DEFAULT_MASTHEAD)
        assert "Sources: https://example.com/weather" in chat
        assert "Couldn't source: the rain chance" in chat
        assert "Couldn't source<br>" not in page

    def test_weather_ear_prints_a_miss_when_research_failed(self):
        data = edition(sections=[{
            "kind": "section", "title": "Weather", "desk": "weather",
            "body": "The city could not be placed.",
            "could_not_source": ["today's high in São Paulo"],
        }])
        page = render.render_html(data, render.DEFAULT_MASTHEAD, "{{WEATHER_EAR}}")
        assert "ear-weather" not in page
        assert "Couldn't source<br>" in page
        assert "today&#x27;s high in São Paulo" in page
        assert "One edition" not in page
        chat = render.render_chat(data, render.DEFAULT_MASTHEAD)
        assert "Couldn't source: today's high in São Paulo" in chat

    def test_weather_icons_are_vendored_atlas_glyphs(self):
        # Forecast keys stay the paper's vocabulary; the drawings are
        # Atlas Icons weather glyphs (MIT), inlined, never fetched.
        notice = (ROOT / "pt-edition" / "assets" / "weather" / "NOTICE").read_text()
        assert "Atlas Icons" in notice
        assert "MIT" in notice
        for key in render.FORECAST_ICONS:
            svg = render.weather_icon(key)
            assert 'class="wx-icon"' in svg
            assert 'viewBox="0 0 1024 1024"' in svg
            assert 'fill="currentColor"' in svg
            assert "<path" in svg
            assert "https://" not in svg
            assert 'circle cx="12"' not in svg
            assert (ROOT / "pt-edition" / "assets" / "weather" / f"{key}.svg").is_file()

    def test_calendar_schedule_draws_kind_icons(self):
        data = edition(sections=[{
            "kind": "section", "title": "Agenda", "desk": "calendar",
            "body": "9am — Product sync.",
            "schedule": [
                {"time": "9am", "title": "Product <sync>", "icon": "meeting"},
                {"time": "11am", "title": "Investor call", "icon": "call"},
            ],
            "sources": ["Calendar.app"],
        }])
        page = render.render_html(data, render.DEFAULT_MASTHEAD, "{{DESKS_INLINE}}")
        assert 'class="cal-list"' in page
        assert page.count('class="cal-icon"') == 2
        assert 'class="cal-body"' in page
        assert "Product &lt;sync&gt;" in page
        assert "Product <sync>" not in page
        assert "<img" not in page
        assert "Sources: Calendar.app" in page
        chat = render.render_chat(data, render.DEFAULT_MASTHEAD)
        assert "Sources: Calendar.app" in chat

    def test_calendar_schedule_strip_caps_a_full_day(self):
        # Issue #7: a full Google day made the desks-row (break-inside:
        # avoid, WeasyPrint table-split workaround) jump to the next
        # page and leave the previous one blank. Cap the print strip;
        # chat serializes the uncapped `schedule` (body can omit a row).
        items = [
            {"time": f"{8 + i}:00", "title": f"Meeting {i}", "icon": "meeting"}
            for i in range(8)
        ]
        data = edition(sections=[{
            "kind": "section", "title": "Agenda", "desk": "calendar",
            "body": "Meeting 0.\n\nMeeting 7.",
            "schedule": items,
            "sources": ["Google Calendar"],
        }])
        page = render.render_html(data, render.DEFAULT_MASTHEAD, "{{DESKS_INLINE}}")
        assert page.count('class="cal-item"') == render.SCHEDULE_STRIP_MAX
        assert "Meeting 0" in page
        assert "Meeting 5" in page
        assert "Meeting 6" not in page
        assert "Meeting 7" not in page
        chat = render.render_chat(data, render.DEFAULT_MASTHEAD)
        assert "Meeting 6" in chat
        assert "Meeting 7" in chat

    def test_mail_messages_draw_an_envelope(self):
        data = edition(sections=[{
            "kind": "section", "title": "Letters", "desk": "mail",
            "body": "Ana — hello.",
            "messages": [{"sender": "Ana <b>Costa</b>", "subject": "Hello <script>"}],
            "sources": ["Gmail"],
        }])
        page = render.render_html(data, render.DEFAULT_MASTHEAD, "{{DESKS_INLINE}}")
        assert 'class="mail-list"' in page
        assert 'class="mail-icon"' in page
        assert 'class="mail-body"' in page
        assert "Ana &lt;b&gt;Costa&lt;/b&gt;" in page
        assert "Hello &lt;script&gt;" in page
        assert "<script>" not in page
        assert "<img" not in page
        assert "Sources: Gmail" in page
        chat = render.render_chat(data, render.DEFAULT_MASTHEAD)
        assert "Sources: Gmail" in chat

    def test_desk_headers_carry_a_drawn_mark(self):
        data = edition(sections=[
            {"kind": "section", "title": "Weather", "desk": "weather", "body": "w",
             "sources": []},
            {"kind": "section", "title": "Agenda", "desk": "calendar", "body": "c",
             "sources": []},
            {"kind": "section", "title": "Letters", "desk": "mail", "body": "m",
             "sources": []},
        ])
        page = render.render_html(data, render.DEFAULT_MASTHEAD, "{{DESKS_INLINE}}")
        assert 'class="desk-icon"' in page
        assert page.count('class="desk-icon"') == 2
        assert 'stroke="#ffffff"' in page

    def test_chat_edition_has_no_icons(self):
        data = edition(sections=[{
            "kind": "section", "title": "Agenda", "desk": "calendar",
            "body": "9am — Product sync.",
            "schedule": [{"time": "9am", "title": "Product sync", "icon": "meeting"}],
            "sources": ["Calendar.app"],
        }])
        text = render.render_chat(data, render.DEFAULT_MASTHEAD)
        assert "<svg" not in text
        assert "Product sync" in text

    def test_desks_render_in_newspaper_order(self):
        data = edition(sections=[
            {"kind": "section", "title": "News", "desk": "news", "body": "n",
             "sources": []},
            {"kind": "section", "title": "Mail", "desk": "mail", "body": "m",
             "sources": []},
            {"kind": "section", "title": "Weather", "desk": "weather", "body": "w",
             "sources": []},
            {"kind": "section", "title": "Diary", "desk": "calendar", "body": "c",
             "sources": []},
        ])
        text = render.render_chat(data, render.DEFAULT_MASTHEAD)
        weather_at = text.index("Weather")
        diary_at = text.index("Diary")
        mail_at = text.index("Mail")
        news_at = text.index("News")
        assert weather_at < diary_at < mail_at < news_at

    def test_location_in_header_and_placeholder(self):
        data = edition(location="Sao Paulo")
        text = render.render_chat(data, render.DEFAULT_MASTHEAD)
        assert text.startswith("THE TIMES \u2014 Sep 11, 2026 \u2014 Sao Paulo")
        page = render.render_html(data, "The Daily", "{{LOCATION}}|{{SECTIONS}}")
        assert page.startswith("Sao Paulo|")

    def test_blank_paragraphs_split(self):
        data = edition(sections=[{
            "kind": "section", "title": "Diary", "desk": "calendar",
            "body": "Today: dentist at 9.\n\nUpcoming: flight on Friday.",
            "sources": ["Calendar.app"],
        }])
        page = render.render_html(data, render.DEFAULT_MASTHEAD, "{{DESKS_INLINE}}")
        assert "Today: dentist at 9." in page
        assert "Upcoming: flight on Friday." in page
        assert "<a href=" not in page

    def test_http_sources_still_link(self):
        page = render.render_html(edition(), render.DEFAULT_MASTHEAD, "{{LEAD}}")
        assert 'href="https://example.com/weather"' in page

    AGENDA = {"kind": "section", "title": "Agenda", "desk": "calendar", "headline": "One call",
              "body": "10:00 Call", "schedule": [{"time": "10:00", "title": "Call", "icon": "call"}],
              "sources": ["Calendar.app"]}
    GAME = {"kind": "section", "title": "Games", "desk": "sports", "body": "Final.",
            "games": [{"home": "Otters", "away": "Foxes", "status": "final", "home_score": 3, "away_score": 1}],
            "sources": ["https://example.com/scores"]}
    NEWS = {"kind": "section", "topic_id": "t_8c1d", "title": "Harbor", "body": "The ferry moved.",
            "sources": ["https://example.com/n"]}
    TEMPLATE = "{{AGENDA}}|{{BODY}}"

    def _page(self, *sections):
        return render.render_html(edition(sections=list(sections)), render.DEFAULT_MASTHEAD, self.TEMPLATE)

    def test_the_agenda_leads_the_page_above_the_news(self):
        page = self._page(self.NEWS, self.AGENDA)
        agenda, body = page.split("|")
        assert 'class="agenda"' in agenda and "section--calendar" in agenda and "Call" in agenda
        assert "ferry moved." in body and "Call" not in body

    def test_sports_scores_print_in_a_rail_beside_the_news(self):
        body = self._page(self.NEWS, self.GAME).split("|")[1]
        assert 'class="side-rail"' in body and "section--sports" in body and "page-body--full" not in body
        assert body.index("ferry moved.") < body.index("section--sports")

    def test_without_sports_the_news_takes_the_whole_width(self):
        body = self._page(self.NEWS, self.AGENDA).split("|")[1]
        assert "page-body--full" in body and "side-rail" not in body

    def test_a_paper_with_only_an_agenda_prints_no_empty_news_block(self):
        agenda, body = self._page(self.AGENDA).split("|")
        assert "agenda" in agenda and body == ""
        assert "nothing to report" not in agenda.lower() and "top-row" not in body

    def test_sports_without_news_still_print(self):
        body = self._page(self.AGENDA, self.GAME).split("|")[1]
        assert "section--sports" in body and "top-row" not in body

    def test_legacy_sudoku_placeholder_is_consumed_without_a_puzzle(self):
        page = render.render_html(edition(), render.DEFAULT_MASTHEAD, "X{{SUDOKU}}Y")
        assert page == "XY"

    def test_dynamic_placeholder_text_is_not_re_evaluated(self):
        page = render.render_html(edition(sections=[
            {"kind": "section", "topic_id": "t_8c1d", "title": "Lead", "desk": "news",
             "body": "Literal {{MAIL}} marker.", "sources": []},
            {"kind": "section", "title": "Letters", "desk": "mail",
             "body": "Private inbox metadata.", "sources": []},
        ]), render.DEFAULT_MASTHEAD, "{{LEAD}}|{{MAIL}}")
        assert page.count("Private inbox metadata.") == 1
        assert "{{MAIL}} marker." in page

    def test_longest_news_story_is_the_lead(self):
        data = edition(sections=[
            {"kind": "section", "title": "Short first", "desk": "news",
             "body": "Brief.", "sources": []},
            {"kind": "section", "title": "Longest second", "desk": "news",
             "body": "This story has enough detail to be the longest of the three.",
             "sources": []},
            {"kind": "section", "title": "Short third", "desk": "news",
             "body": "Also brief.", "sources": []},
        ])
        page = render.render_html(
            data, render.DEFAULT_MASTHEAD, "<main>{{LEAD}}</main><aside>{{NEWS_PAIR}}</aside>",
        )
        lead, pair = page.split("</main><aside>")
        assert "Longest second" in lead
        assert "Short first" in pair
        assert "Short third" in pair

    def test_pdf_writes_all_rendered_pages(self, tmp_path, monkeypatch):
        written = []

        class FakeDocument:
            pages = [object(), object()]

            def write_pdf(self, path):
                written.append(path)

        class FakeHTML:
            def __init__(self, *, string):
                self.string = string

            def render(self):
                return FakeDocument()

        monkeypatch.setitem(sys.modules, "weasyprint", types.SimpleNamespace(HTML=FakeHTML))
        path = tmp_path / "edition.pdf"
        render.write_pdf("<p>two pages</p>", path)
        assert written == [str(path)]


class TestMain:
    def test_prints_chat_to_stdout(self, tmp_path, capsys):
        path = write(tmp_path, edition())
        assert render.main([str(path)]) == 0
        assert "THE TIMES" in capsys.readouterr().out

    def test_writes_chat_file(self, tmp_path):
        path = write(tmp_path, edition())
        out = tmp_path / "chat.txt"
        render.main([str(path), "--chat", str(out)])
        assert "Weather in Sao Paulo" in out.read_text()

    def test_writes_the_chat_only_mail_companion(self, tmp_path):
        path = write(tmp_path, edition(sections=[
            {"kind": "section", "topic_id": "t_8c1d", "title": "Lead", "desk": "news",
             "body": "Printed.", "sources": []},
            {"kind": "section", "title": "Letters", "desk": "mail",
             "body": "Inbox summary.", "sources": []},
            {"kind": "section", "title": "Scores", "desk": "sports",
             "body": "Final score.", "sources": []},
        ]))
        out = tmp_path / "edition.companion.txt"
        render.main([str(path), "--companion", str(out)])
        assert "Inbox summary." in out.read_text()
        assert "Final score." not in out.read_text()  # sports prints on the page
        assert "Printed." not in out.read_text()

    def test_no_chat_only_desks_remove_a_stale_companion(self, tmp_path):
        path = write(tmp_path, edition(sections=[
            {"kind": "section", "topic_id": "t_8c1d", "title": "Lead", "desk": "news",
             "body": "Printed.", "sources": []},
        ]))
        out = tmp_path / "edition.companion.txt"
        out.write_text("old private desk")
        render.main([str(path), "--companion", str(out)])
        assert not out.exists()

    def test_writes_html(self, tmp_path):
        path = write(tmp_path, edition())
        out = tmp_path / "edition.html"
        render.main([str(path), "--html", str(out)])
        html = out.read_text()
        assert "Weather in Sao Paulo" in html
        assert "Sudoku" not in html

    @pytest.mark.parametrize("data, named", [
        ({"date": "x", "sections": []}, "date is not a strict YYYY-MM-DD string"),
    ])
    def test_malformed_refused_by_name(self, tmp_path, data, named):
        path = write(tmp_path, data)
        with pytest.raises(SystemExit) as refused:
            render.main([str(path), "--html", str(tmp_path / "out.html")])
        assert f"invalid edition.json: {named}" in str(refused.value)
        assert not (tmp_path / "out.html").exists()

    def test_unreadable_refused(self, tmp_path):
        with pytest.raises(SystemExit, match="could not read"):
            render.main([str(tmp_path / "missing.json")])

    def test_deterministic(self, tmp_path):
        path = write(tmp_path, edition())
        first = tmp_path / "a.html"
        second = tmp_path / "b.html"
        render.main([str(path), "--html", str(first)])
        render.main([str(path), "--html", str(second)])
        assert first.read_text() == second.read_text()

    @pytest.mark.parametrize("fields", [{"date": "2000-01-01"}, {}])
    def test_refuses_a_desk_file_dated_for_another_day_or_undated(self, tmp_path, fields):
        path = _paper_with_desk_file(tmp_path, edition_with_weather(), fields)
        with pytest.raises(SystemExit) as exc:
            render.main([str(path), "--config", str(tmp_path / "none.json")])
        assert "stale desk notes" in str(exc.value)


    def test_a_news_only_edition_ignores_yesterdays_desk_files(self, tmp_path):
        # A one-topic subscription renders no standing desk; a leftover file
        # from yesterday's daily paper must not block it.
        path = _paper_with_desk_file(tmp_path, edition(), {"date": "2000-01-01"})
        render.main([str(path), "--config", str(tmp_path / "none.json")])

def _paper_with_desk_file(tmp_path, ed, fields):
    run = tmp_path / "run"
    (run / "desk-calendar").mkdir(parents=True)
    (run / "desk-calendar" / "events.json").write_text(
        json.dumps({**fields, "events": []}), encoding="utf-8")
    (run / "paper").mkdir()
    path = run / "paper" / "edition.json"
    path.write_text(json.dumps(ed), encoding="utf-8")
    return path




class TestFillNewsDesk:
    def test_a_topic_id_section_gets_news_only_when_desk_is_missing_or_null(self):
        data = edition(sections=[
            {"kind": "section", "topic_id": "t_1", "title": "x", "body": "y", "sources": []},
            {"kind": "section", "topic_id": "t_2", "desk": None, "title": "x", "body": "y", "sources": []},
            {"kind": "section", "topic_id": "t_3", "desk": "weather", "title": "x", "body": "y", "sources": []},
        ])
        render.fill_news_desk(data)
        assert data["sections"][0]["desk"] == "news"
        assert data["sections"][1]["desk"] == "news"
        assert data["sections"][2]["desk"] == "weather"


ENGLISH_LABELS = ("Sources:", "Couldn't source", "Couldn&#x27;t source",
                  "Nothing to report this time", "nothing to report this time")


class TestLabelsFollowTheOwnersLanguage:
    """The page's own vocabulary comes from owner_phrases.py: curated English and
    Portuguese, and whatever language the paper wrote its phrases in."""

    @staticmethod
    def _every_label_edition():
        page = edition(sections=[])
        for desk in ("weather", "calendar", "mail", "sports", "news"):
            page["sections"].append({
                "kind": "assignment", "topic_id": f"t_{desk}", "run_on": "2026-09-11", "desk": desk,
                "title": desk, "body": " ", "sources": ["https://shop.example/x"],
                "could_not_source": ["o preço do modelo Pro"],
            })
        return page

    @staticmethod
    def _render(page, language):
        html = render.render_html(page, render.DEFAULT_MASTHEAD,
                                  "{{LEAD}}{{WEATHER_EAR}}{{DESKS_INLINE}}",
                                  language=language)
        chat = render.render_chat(page, render.DEFAULT_MASTHEAD, language=language)
        empty = render.render_chat(edition(sections=[]), render.DEFAULT_MASTHEAD, language=language)
        return html + chat + empty

    def test_a_written_language_leaves_no_english_label(self, tmp_path, monkeypatch):
        phrases = load_module("owner_phrases", "pt-shared/scripts/owner_phrases.py")
        monkeypatch.setenv("PT_HOME", str(tmp_path))
        table = {k: (f"〔{k}〕" if k.startswith("page.") else v) for k, v in phrases.SOURCE.items()}
        (tmp_path / "owner-phrases.json").write_text(
            json.dumps({"language": "Mandarin Chinese", "phrases": table}, ensure_ascii=False))
        out = self._render(self._every_label_edition(), "Mandarin Chinese")
        for english in ENGLISH_LABELS:
            assert english not in out, english
        for key in ("sources", "could_not_source", "nothing_to_report"):
            assert f"〔page.{key}〕" in out, key

    def test_portuguese_gets_the_curated_labels(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PT_HOME", str(tmp_path))
        out = self._render(self._every_label_edition(), "Português")
        for english in ENGLISH_LABELS:
            assert english not in out, english
        for label in ("Fontes:", "Sem fonte", "Nada a relatar desta vez"):
            assert label in out, label

    def test_no_language_reads_as_today(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PT_HOME", str(tmp_path))
        out = self._render(self._every_label_edition(), "")
        for english in ("Sources:", "Couldn't source", "Nothing to report this time."):
            assert english in out, english


