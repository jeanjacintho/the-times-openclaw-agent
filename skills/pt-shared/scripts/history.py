#!/usr/bin/env python3
"""history.py -- what one news section printed on recent days, from the wiki.

usage: history.py recent --topic <topic_id>

Prints JSON, oldest first, reading the edition pages record_edition.py writes
(projects/thetimes/editions/<date>.md):
[{"date", "headline", "printed": [{"claim", "url"}]}], what record_edition.py
recorded under that topic id in the page's frontmatter, for today and the 7
days before it -- so the next pass knows which sources it has already
spent and which claims it has already made -- a section with no memory
reprints the same story every morning (issue #69).
The window reaches through today on purpose: the pass most likely to reprint
this morning's section is an afternoon focused paper or a live copy later the
same day, and today's page is exactly where that repeat would be caught.
record_edition.py writes those pages only once a paper was delivered, so a
block the owner never received is never history. A day with no page, or no
block for the topic, is left out. When the Mac does not answer:
`error: history unavailable — <why>`, non-zero.

"Today" is the owner's own day (`owner_time.owner_today()`), not the
container's -- see that module's docstring for why, and for the same
`error: history unavailable — <why>` refusal on a config that can't be
trusted rather than a guessed window.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from latch_mcp import LatchError
from owner_time import owner_today
from wiki import EDITIONS, connect, split_page

DAYS = 7


def _section(text, topic):
    """This topic's record on the page (headline and every sourced claim), or None."""
    return split_page(text)[0].get("sections", {}).get(topic)


def recent(wiki, today, topic):
    out = []
    for back in range(DAYS, -1, -1):
        day = (today - timedelta(days=back)).isoformat()
        text = wiki.read(f"{EDITIONS}/{day}.md")
        entry = _section(text, topic) if text else None
        if entry:
            out.append({"date": day, **entry})
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="What one news section printed lately.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    recent_parser = sub.add_parser("recent")
    recent_parser.add_argument("--topic", required=True, help="a news section's topic id")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(recent(connect(), owner_today(), args.topic), ensure_ascii=False))
    except (LatchError, OSError, ValueError, KeyError, TypeError) as exc:
        sys.exit(f"error: history unavailable — {exc}")


if __name__ == "__main__":
    main()
