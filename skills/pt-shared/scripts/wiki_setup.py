#!/usr/bin/env python3
"""wiki_setup.py -- make the owner's wiki ready for The Times.

usage: wiki_setup.py

Idempotent and cheap when there is nothing to do (a few page reads), so every
caller runs it: record_edition.py before it writes.

  - no ~/Plow/wiki          -> `wiki init ~/Plow/wiki` through Latch's plugin
  - the paper's schema and page, when absent, from pt-shared/assets/wiki/
  - projects/thetimes declared in wiki.toml, when its parsed roots lack it
    (whatever spelling declares them), appended last so a run that failed
    halfway runs again; no other line of the file is touched.

Prints WIKI:ready or `WIKI:set up <what>`. Any failure exits non-zero with
`error: wiki not ready — <why>`.
"""
from __future__ import annotations

import argparse
import datetime
import sys
import tomllib
from pathlib import Path

from owner_chat import home_channel
from latch_mcp import LatchError
from wiki import OVERVIEW, ROOT, SCHEMA, WIKI, WRITER, connect

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "wiki"


def _seed(wiki, rel, asset, chat):
    """Write `rel` from its seed when the wiki lacks it."""
    if wiki.read(rel) is not None:
        return []
    text = (ASSETS / asset).read_text(encoding="utf-8")
    text = text.replace("{today}", datetime.date.today().isoformat()).replace("{chat}", chat)
    wiki.write(rel, text)
    return [rel]


def ensure(wiki, chat):
    did = []
    toml = wiki.read("wiki.toml")
    if toml is None:
        code, out = wiki.run("init", WIKI, write=True)
        if code != 0:
            raise LatchError(f"wiki init: {out.strip()}")
        did.append(WIKI)
    did += _seed(wiki, SCHEMA, "schema.md", chat)
    did += _seed(wiki, OVERVIEW, "overview.md", chat)
    toml = wiki.read("wiki.toml")  # again after the seeds' calls: append to what is there now
    if ROOT not in tomllib.loads(toml).get("roots", {}):
        wiki.write("wiki.toml", f'{toml.rstrip()}\n\n[roots."{ROOT}"]\nwriter = "{WRITER}"\n')
        did.append(f"{ROOT} in wiki.toml")
    return did


def main(argv=None):
    parser = argparse.ArgumentParser(description="Make the owner's wiki ready for the paper.")
    parser.parse_args(argv)
    try:
        did = ensure(connect(), home_channel())
    except LatchError as exc:
        sys.exit(f"error: wiki not ready — {exc}")
    print("WIKI:" + ("ready" if not did else "set up " + ", ".join(did)))


if __name__ == "__main__":
    main()
