#!/usr/bin/env python3
"""render_edition.py -- content in, newspaper out, the same layout every day.

The whole point of separating this from the language model: the model fills
an `edition.json` (headlines, sentences, sources, tags) and this script --
fixed code over a fixed `template.html` -- turns it into the chat text, the
printable HTML and (when weasyprint is present) the PDF. The model never
writes HTML. Same JSON + same template = the same layout, byte for byte, so
two editions differ only in their content, exactly like a printed paper.

    render_edition.py <edition.json> [--chat OUT] [--html OUT] [--pdf OUT] [--config PATH]

With no output flags the chat edition goes to stdout -- the cron-fired
session's final response *is* the chat leg, so this is the normal path. The
HTML is the print leg and the PDF the attachment leg; both are opt-in.

Every string that came from the web is HTML-escaped here, once, in code --
headlines, bodies, tags, sources, the lot. A researched page is untrusted
input and the HTML renders on the owner's Mac; an unescaped quote is
injection, not typography. The template is loaded from beside this script
and is owner-editable (copy-if-absent, so redeploys never clobber it); the
masthead comes from PT_MASTHEAD or the default, never from the JSON, so the
chat text and the printed page can never disagree about the paper's name.

A malformed edition.json is refused loudly and by name, the way the config
gate refuses a malformed config: a half-rendered page shipped is worse than
a run that says what was wrong and waits for the next one.
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import os
import pathlib
import re
import sys
import urllib.request
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "pt-shared" / "scripts")
)
from owner_phrases import phrase  # noqa: E402
from pt_paths import config_file  # noqa: E402
DEFAULT_MASTHEAD = "THE TIMES"
KINDS = ("section", "assignment")
# Optional newspaper desks, each gated by its own configured switch.
# Missing switches mean off. news is every owner-chosen section
# and assignment -- same story shape, different page slot.
DESKS = ("news", "weather", "calendar", "mail", "sports")
DESK_ORDER = {"weather": 0, "calendar": 1, "mail": 2, "sports": 3, "news": 4}
CONFIG_DEFAULT = str(config_file())
# Controlled vocabulary for a sports desk game row -- what state the game
# is in, drawn as a label/tag, never free text.
GAME_STATUSES = ("scheduled", "live", "final")
# Controlled vocabulary for the weather forecast strip -- an icon is
# inlined from pt-edition/assets/weather (Atlas Icons, MIT), never
# fetched, so an unrecognized key is a validation failure rather than
# a silently broken picture or a remote image request.
FORECAST_ICONS = ("sun", "partly-cloudy", "cloud", "rain", "storm", "snow")
# Same idea for the calendar desk's schedule rows -- what kind of event this
# is, drawn from CALENDAR_ICONS, never free text.
SCHEDULE_ICONS = ("meeting", "call", "task", "reminder", "note")
# Issue #7: the calendar+letters row is break-inside:avoid (WeasyPrint
# table-split workaround). A full Google day made that row a page tall,
# so it jumped whole and left the previous sheet blank. The print strip
# keeps this many events; the JSON `body` (chat edition) is uncapped.
SCHEDULE_STRIP_MAX = 6
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TOPIC_ID_RE = re.compile(r"^t_[0-9a-f]{4}$")
TEMPLATE = pathlib.Path(__file__).resolve().parent.parent / "template.html"

# calendar.month_abbr is locale-independent C locale by default; pinned here
# so the masthead's date cannot drift with the container's locale.
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def masthead():
    return (os.environ.get("PT_MASTHEAD") or DEFAULT_MASTHEAD).strip() or DEFAULT_MASTHEAD


def pretty_date(raw):
    """'2026-09-11' -> 'Sep 11, 2026', the masthead's date line."""
    year, month, day = (int(part) for part in raw.split("-"))
    return f"{_MONTHS[month - 1]} {day}, {year}"


def _real_date(raw):
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def blank(value):
    """True unless value is a string with something in it."""
    return not (isinstance(value, str) and value.strip())


def validate(edition):
    """The gate for edition.json; returns "; "-joined failures.

    Empty means pass. Never raises for a content problem -- a bad shape is a
    named failure, so the run can say which section is wrong instead of
    crashing on a KeyError deep in rendering.
    """
    failures = []
    if not isinstance(edition, dict):
        return "edition.json is not a JSON object"

    raw_date = edition.get("date")
    if not (isinstance(raw_date, str) and DATE_RE.fullmatch(raw_date)):
        failures.append("date is not a strict YYYY-MM-DD string")
    else:
        try:
            date.fromisoformat(raw_date)
        except ValueError:
            failures.append("date is not a real calendar date")

    location = edition.get("location")
    if location is not None and not isinstance(location, str):
        failures.append("location is not a string")

    sections = edition.get("sections")
    if not isinstance(sections, list):
        return "; ".join(failures + ["sections is not a list"])
    for index, section in enumerate(sections):
        where = f"sections[{index}]"
        if not isinstance(section, dict):
            failures.append(f"{where} is not an object")
            continue
        kind = section.get("kind")
        if kind not in KINDS:
            failures.append(f"{where}.kind is not section|assignment")
        title = section.get("title")
        if blank(title):
            failures.append(f"{where}.title is blank")
        if not isinstance(section.get("body"), str):
            failures.append(f"{where}.body is not a string")
        headline = section.get("headline")
        if headline is not None and not isinstance(headline, str):
            failures.append(f"{where}.headline is not a string")
        layout = section.get("layout")
        if layout is not None and layout not in ("main", "sidebar"):
            failures.append(f"{where}.layout is not main|sidebar")
        desk = section.get("desk")
        if desk is not None and desk not in DESKS:
            failures.append(f"{where}.desk is not one of {DESKS}")
        sources = section.get("sources", [])
        if not isinstance(sources, list) or not all(isinstance(u, str) for u in sources):
            failures.append(f"{where}.sources is not a list of strings")
        could_not = section.get("could_not_source", [])
        if not isinstance(could_not, list) or not all(isinstance(c, str) for c in could_not):
            failures.append(f"{where}.could_not_source is not a list of strings")
        topic_id = section.get("topic_id")
        if topic_id is not None and not (
            isinstance(topic_id, str) and TOPIC_ID_RE.fullmatch(topic_id)
        ):
            failures.append(f"{where}.topic_id is not a t_xxxx id")
        if topic_id is None and (kind == "assignment" or desk in (None, "news")):
            failures.append(f"{where}.topic_id is required for carried news")
        if kind == "assignment":
            run_on = section.get("run_on")
            if not (isinstance(run_on, str) and DATE_RE.fullmatch(run_on)):
                failures.append(f"{where}.run_on is required for an assignment")
        forecast = section.get("forecast")
        if forecast is not None:
            if desk != "weather":
                failures.append(f"{where}.forecast is only valid on the weather desk")
            elif not isinstance(forecast, list) or len(forecast) != 1:
                failures.append(f"{where}.forecast must contain today's forecast")
            else:
                for day_index, day in enumerate(forecast):
                    dwhere = f"{where}.forecast[{day_index}]"
                    if not isinstance(day, dict):
                        failures.append(f"{dwhere} is not an object")
                        continue
                    if blank(day.get("day")):
                        failures.append(f"{dwhere}.day is blank")
                    if blank(day.get("date")):
                        failures.append(f"{dwhere}.date is blank")
                    if day.get("icon") not in FORECAST_ICONS:
                        failures.append(f"{dwhere}.icon is not one of {FORECAST_ICONS}")
                    if not isinstance(day.get("high"), (int, float)):
                        failures.append(f"{dwhere}.high is not a number")
                    if not isinstance(day.get("low"), (int, float)):
                        failures.append(f"{dwhere}.low is not a number")
        schedule = section.get("schedule")
        if schedule is not None:
            if desk != "calendar":
                failures.append(f"{where}.schedule is only valid on the calendar desk")
            elif not isinstance(schedule, list) or not schedule:
                failures.append(f"{where}.schedule is not a non-empty list")
            else:
                for item_index, item in enumerate(schedule):
                    iwhere = f"{where}.schedule[{item_index}]"
                    if not isinstance(item, dict):
                        failures.append(f"{iwhere} is not an object")
                        continue
                    if blank(item.get("time")):
                        failures.append(f"{iwhere}.time is blank")
                    if blank(item.get("title")):
                        failures.append(f"{iwhere}.title is blank")
                    if item.get("icon") not in SCHEDULE_ICONS:
                        failures.append(f"{iwhere}.icon is not one of {SCHEDULE_ICONS}")
        messages = section.get("messages")
        if messages is not None:
            if desk != "mail":
                failures.append(f"{where}.messages is only valid on the mail desk")
            elif not isinstance(messages, list) or not messages:
                failures.append(f"{where}.messages is not a non-empty list")
            else:
                for item_index, item in enumerate(messages):
                    iwhere = f"{where}.messages[{item_index}]"
                    if not isinstance(item, dict):
                        failures.append(f"{iwhere} is not an object")
                        continue
                    if blank(item.get("sender")):
                        failures.append(f"{iwhere}.sender is blank")
                    if blank(item.get("subject")):
                        failures.append(f"{iwhere}.subject is blank")
        games = section.get("games")
        if games is not None:
            if desk != "sports":
                failures.append(f"{where}.games is only valid on the sports desk")
            elif not isinstance(games, list) or not games:
                failures.append(f"{where}.games is not a non-empty list")
            else:
                for item_index, item in enumerate(games):
                    gwhere = f"{where}.games[{item_index}]"
                    if not isinstance(item, dict):
                        failures.append(f"{gwhere} is not an object")
                        continue
                    if blank(item.get("home")):
                        failures.append(f"{gwhere}.home is blank")
                    if blank(item.get("away")):
                        failures.append(f"{gwhere}.away is blank")
                    status = item.get("status")
                    if status not in GAME_STATUSES:
                        failures.append(f"{gwhere}.status is not one of {GAME_STATUSES}")
                    if status in ("live", "final"):
                        if not isinstance(item.get("home_score"), int):
                            failures.append(f"{gwhere}.home_score is required for {status}")
                        if not isinstance(item.get("away_score"), int):
                            failures.append(f"{gwhere}.away_score is required for {status}")
                    note = item.get("note")
                    if note is not None and not isinstance(note, str):
                        failures.append(f"{gwhere}.note is not a string")
        image = section.get("image")
        if image is not None:
            if desk not in (None, "news"):
                failures.append(f"{where}.image is only valid on a news section")
            elif not isinstance(image, dict):
                failures.append(f"{where}.image is not an object")
            else:
                url = image.get("url")
                if not (
                    isinstance(url, str)
                    and url.strip().startswith(("http://", "https://"))
                ):
                    failures.append(f"{where}.image.url is not an http(s) URL")
                credit = image.get("credit")
                if credit is not None and not isinstance(credit, str):
                    failures.append(f"{where}.image.credit is not a string")
    news_count = sum(
        1 for section in sections
        if isinstance(section, dict) and is_news_section(section)
    )
    if news_count > 3:
        failures.append("edition has more than 3 news articles")
    return "; ".join(failures)


def dedupe(values):
    seen = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def desk_of(section):
    """Which newspaper desk this block belongs to. Default news."""
    desk = section.get("desk")
    return desk if desk in DESKS else "news"


def fill_news_desk(edition):
    """A `topic_id` section is always news (pt-edition/SKILL.md); fill a
    dropped `desk` once, here, so record_edition.py's stricter check (only
    `desk == "news"`, no defaulting) can't silently archive less than
    desk_of() just rendered."""
    for section in edition.get("sections") or []:
        if isinstance(section, dict) and section.get("topic_id") and section.get("desk") is None:
            section["desk"] = "news"


def _label(key, language):
    """The page's own vocabulary (Sources:, FIRST STEP, …) in the owner's
    language: owner_phrases.py's page.* lines, curated English and Portuguese or
    the phrases the paper wrote for any other language. The renderer never
    translates."""
    return phrase(f"page.{key}", language)


def _band_title(section, desk, language):
    """A section's heading."""
    return section["title"].strip()


def _nothing_line(language):
    """The empty-section note: the label without its full stop, lower-cased
    first letter, in parentheses -- "(nothing to report this time)"."""
    text = _label("nothing_to_report", language).rstrip(".。 ")
    return f"({text[:1].lower()}{text[1:]})"


def _owner_language(config):
    if not isinstance(config, dict):
        return ""
    owner = config.get("owner")
    if not isinstance(owner, dict):
        return ""
    lang = owner.get("language")
    return lang if isinstance(lang, str) else ""


def _load_json_file(path):
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def stale_desk_files(edition, run_root):
    """Desk files under run_root/desk-*/ dated for a day other than the edition's.

    A desk that fails to gather leaves the previous day's notes.json /
    events.json in place, and the paper would print yesterday's agenda as
    today's. Every desk file must carry today's `date`: a missing one is as
    stale as a wrong one. Called only on a validated edition. A news-only
    edition (a one-topic subscription) renders no standing desk, so leftover
    desk files cannot reach it and are not judged.
    """
    if all(desk_of(s) == "news" for s in edition["sections"]):
        return []
    stale = []
    carried = {f"desk-{desk_of(s)}" for s in edition["sections"]}
    for path in sorted(pathlib.Path(run_root).glob("desk-*/*.json")):
        if path.parent.name not in carried:
            continue
        data = _load_json_file(path)
        if data is None:
            continue
        if data.get("date") != edition["date"]:
            stale.append(f"{path.parent.name}/{path.name} is dated {data.get('date')!r}")
    return stale


def ordered_sections(sections):
    """Weather, calendar, mail, then news -- the paper's fixed departments."""
    return sorted(
        enumerate(sections),
        key=lambda item: (DESK_ORDER.get(desk_of(item[1]), 9), item[0]),
    )


def is_news_section(section):
    """Owner news and assignments -- never a standing desk."""
    return desk_of(section) == "news"


def join_articles(sections, language=""):
    return "\n".join(html_section(s, language=language) for s in sections)


def wrap_desk(html):
    """A desk card exists only when it has copy -- no empty bordered box."""
    html = (html or "").strip()
    if not html:
        return ""
    return f'<div class="desk-slot">{html}</div>'


def body_paragraphs(body):
    """Split a body on blank lines so a desk can have today / upcoming grafs."""
    text = (body or "").strip()
    if not text:
        return []
    return [part.strip() for part in text.split("\n\n") if part.strip()]


def source_markup(url, label=None):
    """http(s) sources are links (text: `label`, else the url); other labels stay plain."""
    escaped = html.escape(label or url)
    if url.startswith(("http://", "https://")):
        return f'<a href="{html.escape(url, quote=True)}">{escaped}</a>'
    return escaped


def chat_section(section, language=""):
    """One topic's block in the chat edition."""
    tag = section.get("tag")
    desk = desk_of(section)
    title = _band_title(section, desk, language)
    kicker = f"{desk} \u2014 " if desk != "news" else ""
    lines = [f"\u25b8 {kicker}{title}" + (f" \u2014 {tag}" if tag else "")]
    headline = (section.get("headline") or "").strip()
    if headline:
        lines.append(f"  {headline}")
    schedule = section.get("schedule") if desk == "calendar" else None
    if schedule:
        for item in schedule:
            lines.append(f"  {item['time'].strip()} {item['title'].strip()}")
    else:
        body = section.get("body", "").strip()
        lines.append(f"  {body}" if body else f"  {_nothing_line(language)}")
    sources = dedupe(section.get("sources", []))
    could_not = section.get("could_not_source", [])
    if sources:
        lines.append(f"  {_label('sources', language)} " + ", ".join(sources))
    if could_not:
        lines.append(f"  {_label('could_not_source', language)} " + "; ".join(could_not))
    return "\n".join(lines)


def render_chat(edition, name, language=""):
    header = f"{name} \u2014 {pretty_date(edition['date'])}"
    location = (edition.get("location") or "").strip()
    if location:
        header = f"{header} \u2014 {location}"
    lines = [header]
    if edition["sections"]:
        for _index, section in ordered_sections(edition["sections"]):
            lines.append("")
            lines.append(chat_section(section, language))
    else:
        lines.append("")
        lines.append(_label("nothing_to_report", language))
    return "\n".join(lines) + "\n"


def render_companion(edition):
    """The mail desk, omitted from the print layout: the owner's inbox stays in chat."""
    sections = [
        section for _index, section in ordered_sections(edition["sections"])
        if desk_of(section) == "mail"
    ]
    if not sections:
        return ""
    return "\n\n".join(chat_section(section) for section in sections) + "\n"


# Forecast drawings: Atlas Icons weather glyphs (MIT), vendored beside
# this skill so the "no external assets" rule in template.html holds.
# FORECAST_ICONS is the only allowed set of filenames.
WEATHER_ICON_DIR = pathlib.Path(__file__).resolve().parent.parent / "assets" / "weather"


def weather_icon(key, size=28):
    """One inline SVG for a forecast day, `size` px square. `key` is
    pre-validated against FORECAST_ICONS by validate()."""
    text = (WEATHER_ICON_DIR / f"{key}.svg").read_text(encoding="utf-8")
    return text.replace(
        "<svg ",
        f'<svg class="wx-icon" width="{size}" height="{size}" ',
        1,
    )


def weather_ear_html(weather_sections, language=""):
    """The masthead's right ear: today's icon and high/low when the
    notes have a forecast. A weather desk that failed research (no
    forecast, named in could_not_source) must not look like a complete
    paper -- the ear prints that miss instead of the slogan. The slogan
    is only for a day with no weather desk at all."""
    fallback = '<span class="ear-box">One edition<br>for one reader</span>'
    for section in weather_sections:
        forecast = section.get("forecast")
        if forecast:
            today = forecast[0]
            icon = weather_icon(today.get("icon"), size=22)
            high = html.escape(str(today["high"]))
            low = html.escape(str(today["low"]))
            return (
                '<span class="ear-box ear-weather">'
                f'<span class="wx-icon-wrap">{icon}</span>'
                '<span class="ear-wx-temps">'
                f'<span class="ear-wx-high">{high}&deg;</span>'
                f'<span class="ear-wx-low">{low}&deg;</span>'
                "</span>"
                "</span>"
            )
    for section in weather_sections:
        misses = [str(m).strip() for m in section.get("could_not_source", []) if str(m).strip()]
        if misses:
            return (
                '<span class="ear-box">'
                f"{html.escape(_label('could_not_source', language).rstrip(':： '), quote=False)}<br>"
                f"{html.escape(misses[0])}"
                "</span>"
            )
    return fallback


# Same drawn-not-fetched approach for the calendar desk: what kind of event
# a schedule row is, so a meeting reads differently from a call or a task
# at a glance -- SCHEDULE_ICONS is the only allowed set of keys.
CALENDAR_ICONS = {
    "meeting": (
        '<circle cx="9" cy="8.5" r="2.6"/><circle cx="17" cy="9.5" r="2.1"/>'
        '<path d="M3.5 19c.4-3 2.6-5 5.5-5s5.1 2 5.5 5"/>'
        '<path d="M14.8 14.3c2.3.2 4 1.9 4.3 4.4"/>'
    ),
    "call": (
        '<path d="M5.5 4.5c1.4-.6 2-.4 2.6.4l1.3 1.9c.4.6.3 1.2-.2 1.8'
        'l-1 1.1c.7 1.8 2.3 3.4 4.1 4.1l1.1-1c.6-.5 1.2-.6 1.8-.2l1.9 1.3'
        'c.8.6 1 1.2.4 2.6-.6 1.4-1.7 2.1-3.1 1.9-4.3-.6-8.1-4.8-9.1-9.1'
        'C4.3 8.3 5 7.2 5.5 4.5z"/>'
    ),
    "task": (
        '<rect x="4.5" y="4.5" width="15" height="15" rx="2"/>'
        '<path d="M8 12.3l2.5 2.5L16.5 9"/>'
    ),
    "reminder": (
        '<path d="M6 17.5V11a6 6 0 0 1 12 0v6.5"/>'
        '<path d="M4.5 17.5h15M10 20.5a2 2 0 0 0 4 0"/>'
    ),
    "note": (
        '<path d="M6 4.5h12v15H6z"/><path d="M9 9h6M9 12.5h6M9 16h3.5"/>'
    ),
}
# A mail item's icon never varies by content (there is no meaningful
# "kind" of letter the way there is a kind of calendar event), so this is
# one constant drawing, not a lookup keyed by untrusted data.
MAIL_ICON = '<path d="M4 6.5h16v11H4z"/><path d="M4.5 7l7.5 6 7.5-6"/>'
# Department mark in the filled desk header -- same drawn-not-fetched
# rule as the strips. Weather already has a per-day icon in the forecast
# grid; calendar and mail get the same kind of mark in the title bar so
# the three boxes read as a set.
DESK_HEADER_ICONS = {
    "weather": (
        '<circle cx="12" cy="12" r="3.6"/>'
        '<path d="M12 3.2v2.2M12 18.6v2.2M5.4 5.4l1.6 1.6M16.9 16.9l1.6 1.6'
        'M3.2 12h2.2M18.6 12h2.2M5.4 18.6l1.6-1.6M16.9 7l1.6-1.6"/>'
    ),
    "calendar": (
        '<rect x="4" y="6" width="16" height="14" rx="1.5"/>'
        '<path d="M8 4v4M16 4v4M4 11h16"/>'
    ),
    "mail": MAIL_ICON,
    "sports": (
        '<circle cx="12" cy="12" r="8.5"/>'
        '<path d="M12 3.5v17M3.5 12h17M6 6.3c2 1.7 4 2.6 6 2.6s4-.9 6-2.6'
        'M6 17.7c2-1.7 4-2.6 6-2.6s4 .9 6 2.6"/>'
    ),
}


def _stroke_svg(css_class, body, size, stroke="currentColor"):
    return (
        f'<svg class="{css_class}" viewBox="0 0 24 24" width="{size}" height="{size}" '
        f'fill="none" stroke="{stroke}" stroke-width="1.5" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        f"{body}</svg>"
    )


def desk_header_icon(desk):
    """Tiny monochrome mark for a standing-desk title bar, or '' for news."""
    body = DESK_HEADER_ICONS.get(desk)
    if not body:
        return ""
    # Title bars are ink; WeasyPrint leaves currentColor as black, so the
    # stroke has to be paper-white here or the mark vanishes into the bar.
    return _stroke_svg("desk-icon", body, 13, stroke="#ffffff")


def calendar_icon(key):
    """One 16x16 inline SVG for a schedule row. `key` is pre-validated
    against SCHEDULE_ICONS by validate(); falls back to the generic note
    icon rather than trust an unchecked caller."""
    body = CALENDAR_ICONS.get(key, CALENDAR_ICONS["note"])
    return _stroke_svg("cal-icon", body, 16)


def schedule_list(items):
    """The calendar desk's agenda: one row per event, icon plus a bold
    time and the title -- every string here came from the day's own
    note, so it is escaped like any other section field.

    Print only the first SCHEDULE_STRIP_MAX rows (issue #7). Extra
    events stay on `schedule` for the chat edition.
    """
    rows = []
    for item in items[:SCHEDULE_STRIP_MAX]:
        icon = calendar_icon(item.get("icon"))
        time_str = html.escape(item["time"].strip())
        title = html.escape(item["title"].strip())
        rows.append(
            '<div class="cal-item">'
            f'<span class="cal-icon-wrap">{icon}</span>'
            '<span class="cal-body">'
            f'<span class="cal-time">{time_str}</span>'
            f'<span class="cal-title">{title}</span>'
            "</span>"
            "</div>"
        )
    return '<div class="cal-list">' + "".join(rows) + "</div>"


def messages_list(items):
    """The mail desk's letters: one row per message, an envelope mark
    plus a bold sender and the subject -- escaped like any other field."""
    icon = (
        '<svg class="mail-icon" viewBox="0 0 24 24" width="18" height="18" '
        'fill="none" stroke="currentColor" stroke-width="1.5" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        f"{MAIL_ICON}</svg>"
    )
    rows = []
    for item in items:
        sender = html.escape(item["sender"].strip())
        subject = html.escape(item["subject"].strip())
        rows.append(
            '<div class="mail-item">'
            f'<span class="mail-icon-wrap">{icon}</span>'
            '<span class="mail-body">'
            f'<span class="mail-sender">{sender}</span>'
            f'<span class="mail-subject">{subject}</span>'
            "</span>"
            "</div>"
        )
    return '<div class="mail-list">' + "".join(rows) + "</div>"


def _esc(text):
    return html.escape(text.strip())


def games_list(games):
    """The sports desk's scoreboard: one row per followed team's game --
    away/home names, and either the kickoff time (game hasn't started)
    or the score (it has). No "live" indicator -- a printed page is
    read after the fact, so a game already under way when this ran is
    shown exactly like a finished one: last known score, no clock, no
    "on air" label that would be stale by the time anyone reads it. No
    logos either -- the renderer never fetches images -- so the teams'
    own names carry the row, the same text-first approach as the mail
    desk's sender line."""
    rows = []
    for game in games:
        home = html.escape(game["home"].strip())
        away = html.escape(game["away"].strip())
        status = game["status"]
        note = (game.get("note") or "").strip()
        if status == "scheduled":
            score_html = html.escape(note) if note else "&mdash;"
        else:
            home_score = html.escape(str(game["home_score"]))
            away_score = html.escape(str(game["away_score"]))
            score_html = f"{away_score}&ndash;{home_score}"
        rows.append(
            '<div class="sp-game">'
            f'<span class="sp-teams"><span class="sp-away">{away}</span>'
            f'<span class="sp-vs">&times;</span>'
            f'<span class="sp-home">{home}</span></span>'
            f'<span class="sp-score">{score_html}</span>'
            "</div>"
        )
    return '<div class="sp-list">' + "".join(rows) + "</div>"


PHOTO_MAX_DIM = 640
PHOTO_TIMEOUT = 8
PHOTO_MAX_BYTES = 6_000_000
# Newspaper-photo-ish landscape ratio (width/height). Fixed here, in
# Python, rather than left to CSS: WeasyPrint doesn't implement
# object-fit either -- measured: object-fit:cover on a sized box let
# the photo keep its own native aspect ratio instead of cropping to
# fill, so a tall or oddly-shaped source photo rendered at whatever
# height that produced (once, at full column width, a portrait photo
# came out nearly a full page tall and pushed nine paragraphs of copy
# onto the next page). Cropping the pixels themselves, once, means the
# template's CSS only ever needs width:100%; height:auto.
PHOTO_RATIO = 2.0


def _crop_to_ratio(image, ratio=PHOTO_RATIO):
    width, height = image.size
    if width / height > ratio:
        new_width = round(height * ratio)
        left = (width - new_width) // 2
        return image.crop((left, 0, left + new_width, height))
    new_height = round(width / ratio)
    top = (height - new_height) // 2
    return image.crop((0, top, width, top + new_height))


def fetch_grayscale_photo(url):
    """Fetch a news photo, crop it to a fixed landscape ratio and flatten
    it to grayscale before it ever reaches the page, then hand back a
    self-contained data: URI -- never a live external reference left
    sitting in the printed HTML/PDF.

    Three reasons this happens here instead of just pointing an <img> at
    the URL and letting the browser/WeasyPrint handle it: (1) the page's
    whole palette is ink/grey/white and WeasyPrint doesn't implement CSS
    `filter` -- measured: `filter: grayscale(1)` on an <img> rendered
    the photo in full, untouched color, so a real photo would be the one
    thing on the page breaking the monochrome rule. (2) WeasyPrint
    doesn't implement `object-fit` either -- measured: `object-fit:cover`
    on a fixed-size box still rendered the photo at its own native
    aspect ratio instead of cropping to fill, so sizing has to happen to
    the actual pixels, not in CSS. (3) a self-contained data: URI means
    the printable HTML doesn't depend on network access a second time if
    it's ever re-rendered or opened later -- same "no guarantee of
    network access" reasoning that kept fonts and other external assets
    out of template.html from the start.

    Never raises: Pillow being absent, a timeout, a 404, a non-image
    response, or a file too large all just mean no photo for that story,
    so one bad photo URL never takes down the rest of the paper."""
    try:
        from PIL import Image  # noqa: PLC0415 -- optional dependency

        req = urllib.request.Request(url, headers={"User-Agent": "ThePlowTimes/1.0"})
        with urllib.request.urlopen(req, timeout=PHOTO_TIMEOUT) as resp:  # noqa: S310
            content_type = resp.headers.get("Content-Type", "")
            if not content_type.startswith("image/"):
                return None
            data = resp.read(PHOTO_MAX_BYTES + 1)
            if len(data) > PHOTO_MAX_BYTES:
                return None
        image = Image.open(io.BytesIO(data))
        image = image.convert("L")
        image = _crop_to_ratio(image)
        image.thumbnail((PHOTO_MAX_DIM, round(PHOTO_MAX_DIM / PHOTO_RATIO)))
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=82)
        encoded = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"
    except Exception:  # noqa: BLE001 -- any fetch/decode failure is just "no photo"
        return None


def html_section(section, drop_cap=False, language=""):
    """One topic's block as escaped HTML. Every dynamic string is escaped.

    ``desk`` (optional, default ``news``) is the newspaper department.
    Calendar, mail and sports fill {{DESKS_INLINE}}; weather draws
    {{WEATHER_EAR}} (not this function); the first news story fills
    {{LEAD}} and the rest fill {{SECTIONS}}. Same story fields, same
    escaping; only the wrapping class and the page slot differ.

    A news story's ``tag`` prints as a kicker -- the small letterspaced
    section label above the headline, the way a broadsheet labels
    departments. On desks the tag stays inline in the title bar.

    The lead paginates as ordinary paragraphs. A multi-cell body table
    had to stay whole (WeasyPrint 62.3 repaints a split cell in the
    wrong column), so a long lead jumped to the next page while the
    front still had room.

    ``drop_cap`` (lead story only) wraps the first character of the first
    paragraph in ``<span class="dropcap">`` for the CSS to float and
    enlarge. This used to be a plain ``::first-letter`` rule, but that
    combined with ``float`` is broken in WeasyPrint: the generated pseudo-
    element's box isn't reserved in the line, so the *second* character
    prints on top of the drop cap instead of beside it (measured: "Consumer"
    rendered as the enlarged "C" overlapping "nsumer", the "o" hidden
    underneath). A real, explicit span floats correctly where the pseudo-
    element didn't.
    """
    desk = desk_of(section)
    title = html.escape(_band_title(section, desk, language), quote=False)
    headline = (section.get("headline") or "").strip()
    paras = body_paragraphs(section.get("body", ""))
    tag = section.get("tag")
    # News stories wear the tag as a kicker above the headline; desks
    # keep it inline in the title bar.
    kicker_html = ""
    tag_html = ""
    if tag:
        if desk == "news":
            kicker_html = f'  <p class="kicker">{html.escape(tag)}</p>'
        else:
            tag_html = f' <span class="tag">{html.escape(tag)}</span>'
    classes = ["section"]
    if desk != "news":
        classes.append("section--desk")
        classes.append(f"section--{desk}")
    elif section.get("layout") == "sidebar":
        classes.append("section--sidebar")
    article_class = " ".join(classes)
    header_icon = desk_header_icon(desk)
    schedule = section.get("schedule") if desk == "calendar" else None
    messages = section.get("messages") if desk == "mail" else None
    games = section.get("games") if desk == "sports" else None
    structured = schedule or messages or games
    # Calendar/mail/sports keep title and headline but drop the body
    # PROSE once a list is present, or the box shows the same event
    # twice. Print sources stay. Chat is unaffected (chat_section).
    # Body stays required in the JSON because chat has no icons to
    # fall back on. Weather never reaches this function -- the ear
    # draws it.
    skip_body = bool(structured)
    blocks = [f'<article class="{article_class}">']
    if kicker_html:
        blocks.append(kicker_html)
    blocks.append(f'  <h2>{header_icon}{title}{tag_html}</h2>')
    if headline:
        blocks.append(f'  <p class="headline">{html.escape(headline)}</p>')
    image = section.get("image") if desk == "news" else None
    if image:
        data_uri = fetch_grayscale_photo(image["url"].strip())
        if data_uri:
            credit = (image.get("credit") or "").strip()
            credit_html = (
                f"<figcaption>{html.escape(credit)}</figcaption>" if credit else ""
            )
            blocks.append(
                f'  <figure class="story-photo"><img src="{data_uri}" alt="">'
                f"{credit_html}</figure>"
            )
    if schedule:
        blocks.append(schedule_list(schedule))
    if messages:
        blocks.append(messages_list(messages))
    if games:
        blocks.append(games_list(games))
    if skip_body:
        pass
    elif paras:
        for index, para in enumerate(paras):
            if drop_cap and index == 0 and para:
                first, rest = para[0], para[1:]
                blocks.append(
                    f'  <p><span class="dropcap">{html.escape(first)}</span>'
                    f"{html.escape(rest)}</p>"
                )
            else:
                blocks.append(f"  <p>{html.escape(para)}</p>")
    else:
        blocks.append(f"  <p>{html.escape(_nothing_line(language), quote=False)}</p>")
    sources = dedupe(section.get("sources", []))
    if sources:
        links = ", ".join(source_markup(url) for url in sources)
        blocks.append(f'  <p class="sources">{html.escape(_label("sources", language), quote=False)} {links}</p>')
    could_not = section.get("could_not_source", [])
    if could_not:
        items = "; ".join(html.escape(item) for item in could_not)
        blocks.append(f'  <p class="unsourced">{html.escape(_label("could_not_source", language), quote=False)} {items}</p>')
    blocks.append("</article>")
    return "\n".join(blocks)


def render_html(edition, name, template_text, language=""):
    ordered = [section for _index, section in ordered_sections(edition["sections"])]
    news = [s for s in ordered if is_news_section(s)]
    weather = [s for s in ordered if desk_of(s) == "weather"]
    calendar = [s for s in ordered if desk_of(s) == "calendar"]
    mail = [s for s in ordered if desk_of(s) == "mail"]
    sports = [s for s in ordered if desk_of(s) == "sports"]

    # The longest story gets the full-width lead; equal lengths preserve
    # roster order, and the other two retain their original relative order.
    if news:
        lead_index = max(
            range(len(news)), key=lambda index: len(news[index].get("body", ""))
        )
        lead = news[lead_index]
        rest = news[:lead_index] + news[lead_index + 1:]
        lead_html = html_section(lead, drop_cap=True, language=language)
    elif calendar or mail or sports:
        lead_html = ""
        rest = []
    else:
        lead_html = f'<article class="section"><p>{html.escape(_label("nothing_to_report", language), quote=False)}</p></article>'
        rest = []

    pair_cells = "".join(
        f'<div class="news-pair-cell">{html_section(section, language=language)}</div>'
        for section in rest
    )
    news_pair_html = (
        f'<div class="news-pair">{pair_cells}</div>' if pair_cells else ""
    )
    weather_html = wrap_desk(join_articles(weather, language))
    calendar_html = wrap_desk(join_articles(calendar, language))
    mail_html = wrap_desk(join_articles(mail, language))
    sports_html = wrap_desk(join_articles(sports, language))
    desks_html = "\n".join(
        part for part in (weather_html, calendar_html, mail_html, sports_html) if part
    )

    # Calendar, mail and sports run as a row of boxed departments under
    # the front page, above the news lead. Empty string when none of
    # them ran today, so the template never prints a bare rule above
    # nothing. Weather isn't here -- it lives in the masthead's ear.
    inline_parts = [part for part in (calendar_html, mail_html, sports_html) if part]
    desks_inline_html = ""
    if inline_parts:
        cells = "".join(f'<div class="desks-cell">{part}</div>' for part in inline_parts)
        desks_inline_html = f'<div class="desks-row">{cells}</div>'
    weather_ear = weather_ear_html(weather, language)

    # The agenda leads the page: a full-width band under the folio. Sports
    # scores sit in a rail beside the news; with nothing beside them the news
    # takes the whole width, and a paper with no news prints no empty rule.
    agenda_html = f'<div class="agenda">{calendar_html}</div>' if calendar_html else ""
    main_html = "\n".join(part for part in (
        f'<div class="top-row"><div class="lead-cell">{lead_html}</div></div>' if lead_html else "",
        news_pair_html,
    ) if part)
    if main_html and sports_html:
        body_html = (f'<div class="page-body"><main class="news-column">{main_html}</main>'
                     f'<aside class="side-rail">{sports_html}</aside></div>')
    elif main_html or sports_html:
        body_html = (f'<div class="page-body page-body--full"><main class="news-column">'
                     f'{main_html or sports_html}</main></div>')
    else:
        body_html = ""

    location = html.escape((edition.get("location") or "").strip() or "One copy")
    slots = {
        "{{AGENDA}}": agenda_html,
        "{{BODY}}": body_html,
        "{{MASTHEAD}}": html.escape(name),
        "{{DATE}}": html.escape(pretty_date(edition["date"])),
        "{{LOCATION}}": location,
        "{{LEAD}}": lead_html,
        "{{WEATHER_EAR}}": weather_ear,
        "{{DESKS_INLINE}}": desks_inline_html,
        "{{NEWS_PAIR}}": news_pair_html,
        "{{CALENDAR_RAIL}}": calendar_html,
        "{{SECTIONS}}": news_pair_html,
        "{{WEATHER}}": weather_html,
        "{{CALENDAR}}": calendar_html,
        "{{MAIL}}": mail_html,
        "{{SPORTS}}": sports_html,
        "{{SIDEBAR}}": desks_html,
        "{{SUDOKU}}": "",
    }
    slot_re = re.compile("|".join(re.escape(slot) for slot in slots))
    return slot_re.sub(lambda match: slots[match.group(0)], template_text)


def write_pdf(html_text, path):
    """The PDF leg. weasyprint is optional; its absence is a named failure."""
    pathlib.Path(path).unlink(missing_ok=True)
    try:
        from weasyprint import HTML  # noqa: PLC0415 -- optional dependency
    except ImportError:
        sys.exit(
            "error: weasyprint is not installed; cannot write the PDF edition "
            "(the personalized-paper plan §5 has the Chrome-on-Mac fallback)."
        )
    document = HTML(string=html_text).render()
    document.write_pdf(str(path))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("edition", help="path to edition.json")
    parser.add_argument("--chat", default=None, help="write the chat text here")
    parser.add_argument("--html", default=None, help="write the printable HTML here")
    parser.add_argument("--pdf", default=None, help="write a PDF here (needs weasyprint)")
    parser.add_argument("--companion", default=None,
                        help="write the chat-only mail desk here when present")
    parser.add_argument("--config", default=CONFIG_DEFAULT,
                        help="pt/config.json; its owner.language picks the page's labels")
    args = parser.parse_args(argv)

    try:
        edition = json.loads(pathlib.Path(args.edition).read_text())
    except (OSError, ValueError) as exc:
        sys.exit(f"error: could not read {args.edition}: {exc!r}")

    if isinstance(edition, dict):
        fill_news_desk(edition)
    config = _load_json_file(args.config)
    if config is None and pathlib.Path(args.config).exists():
        sys.exit("error: newspaper config is not a readable JSON object")
    config = config or {}
    for desk in DESKS:
        block = config.get(desk)
        if block is not None and (not isinstance(block, dict) or
                                  not isinstance(block.get("configured"), bool)):
            sys.exit(f"error: {desk}.configured is not a boolean")

    failures = validate(edition)
    if failures:
        sys.exit(f"error: invalid edition.json: {failures}")
    # Explicit opt-in, including older configs with no weather/calendar switches.
    edition["sections"] = [s for s in edition["sections"]
                           if desk_of(s) == "news" or
                           (config.get(desk_of(s)) or {}).get("configured") is True]

    stale = stale_desk_files(edition, pathlib.Path(args.edition).resolve().parent.parent)
    if stale:
        sys.exit(f"error: stale desk notes for edition {edition['date']}: {stale}; "
                 "re-run that desk's gather instead of reusing yesterday's file")

    name = masthead()
    chat_text = render_chat(edition, name, _owner_language(config))

    if args.chat:
        pathlib.Path(args.chat).write_text(chat_text)
    else:
        sys.stdout.write(chat_text)

    if args.companion:
        companion_path = pathlib.Path(args.companion)
        companion_path.unlink(missing_ok=True)
        companion = render_companion(edition)
        if companion:
            companion_path.write_text(companion)

    if args.html or args.pdf:
        try:
            template_text = TEMPLATE.read_text()
        except OSError as exc:
            sys.exit(f"error: could not read template {TEMPLATE}: {exc!r}")
        page = render_html(edition, name, template_text, language=_owner_language(config))
        if args.html:
            pathlib.Path(args.html).write_text(page)
        if args.pdf:
            write_pdf(page, args.pdf)

    return 0


if __name__ == "__main__":
    sys.exit(main())
