#!/usr/bin/env python3
"""set_sports.py -- the teams the sports desk follows, changed from chat.

    set_sports.py add <team> <league>
    set_sports.py remove <team>
    set_sports.py list

"Put Flamengo's score in my paper" / "stop the Lakers" is one call here, never
a hand-edited config.json. `league` is the ESPN league slug the desk reads
(`bra.1`, `nba`, `eng.1` ...). Adding the first team turns the desk on
(`sports.configured`); removing the last turns it off. The result is validated by
pt_config_gate.py BEFORE it replaces the file, and written atomically. Prints
one line, `SPORTS:` then the followed teams, or `SPORTS:none`:

    SPORTS:Flamengo (bra.1), Lakers (nba)

A bad argument, a missing config, a team past the cap or one the gate refuses
changes nothing: `error: …` on stderr, exit 1. Adding a team already followed
only updates its league.
"""
from __future__ import annotations

import json
import os
import sys

import pt_config_gate as _gate
from pt_paths import config_file

MAX_TEAMS = _gate.MAX_FOLLOWED_TEAMS


def fail(message):
    print(f"error: {message}", file=sys.stderr)
    return 1


def _followed(config):
    block = config.get("sports")
    followed = block.get("followed") if isinstance(block, dict) else None
    return [dict(item) for item in followed] if isinstance(followed, list) else []


def _summary(followed):
    return "SPORTS:" + (", ".join(f"{item['team']} ({item['league']})" for item in followed) or "none")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    usage = "usage: set_sports.py add <team> <league> | remove <team> | list"
    if not argv or argv[0] not in ("add", "remove", "list"):
        return fail(usage)
    command, args = argv[0], [a.strip() for a in argv[1:]]
    if (command == "add" and len(args) != 2) or (command == "remove" and len(args) != 1) \
            or (command == "list" and args) or not all(args):
        return fail(usage)
    path = config_file()
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return fail(f"no config at {path}; finish setup first")
    except (OSError, ValueError) as error:
        return fail(f"config is not readable: {error}")
    if not isinstance(config, dict):
        return fail("config is not a JSON object")
    followed = _followed(config)
    if command == "list":
        print(_summary(followed))
        return 0
    team = args[0]
    mine = [i for i in followed if str(i.get("team", "")).casefold() == team.casefold()]
    if command == "add":
        if mine:
            mine[0]["league"] = args[1]
        elif len(followed) >= MAX_TEAMS:
            return fail(f"the paper follows at most {MAX_TEAMS} teams; remove one first")
        else:
            followed.append({"team": team, "league": args[1]})
    else:
        if not mine:
            return fail(f"{team!r} is not followed")
        followed = [i for i in followed if i not in mine]
    config["sports"] = {"configured": bool(followed), "followed": followed}
    failures = _gate.gate(config)
    if failures:
        return fail(failures)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    print(_summary(followed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
