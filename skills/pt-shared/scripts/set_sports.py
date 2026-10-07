#!/usr/bin/env python3
"""Follow teams or entire leagues, with validated atomic preferences.

set_sports.py add <team> <league> | remove <team>
set_sports.py add-league <name> <league> | remove-league <league> | list
Append --draft during setup. Five teams and five leagues maximum; missing
leagues preserves the old team-only schema. The desk stays on until both
lists are empty. ESPN slugs include bra.1, nba and nfl.
"""
from __future__ import annotations

import json
import os
import sys

from set_desks import validate_preferences
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
    return "SPORTS:" + (", ".join(f"{item.get('team', item.get('name'))} ({item['league']})" for item in followed) or "none")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    draft = "--draft" in argv
    if draft:
        argv.remove("--draft")
    usage = "usage: set_sports.py add <team> <league> | remove <team> | add-league <name> <league> | remove-league <league> | list [--draft]"
    if not argv or argv[0] not in ("add", "remove", "add-league", "remove-league", "list"):
        return fail(usage)
    command, args = argv[0], [a.strip() for a in argv[1:]]
    if (command in ("add", "add-league") and len(args) != 2) or (command in ("remove", "remove-league") and len(args) != 1) \
            or (command == "list" and args) or not all(args):
        return fail(usage)
    path = config_file()
    if draft:
        path = path.with_name(".setup-draft.json")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return fail(f"no config at {path}; finish setup first")
    except (OSError, ValueError) as error:
        return fail(f"config is not readable: {error}")
    if not isinstance(config, dict):
        return fail("config is not a JSON object")
    try:
        followed = _followed(config)
    except (TypeError, ValueError):
        return fail("sports.followed is malformed")
    block = config.get("sports") or {}
    leagues = block.get("leagues", []) if isinstance(block, dict) else []
    if not isinstance(leagues, list) or not all(isinstance(i, dict) for i in leagues):
        return fail("sports.leagues is malformed")
    if command == "list":
        try:
            failures = validate_preferences(config, draft)
        except _gate.GateError as error:
            return fail(str(error))
        if failures:
            return fail(failures)
        print(_summary(followed + leagues))
        return 0
    league_command = command in ("add-league", "remove-league")
    items = leagues if league_command else followed
    key = "league" if command == "remove-league" else "name" if league_command else "team"
    mine = [i for i in items if str(i.get(key, "")).casefold() == args[0].casefold()]
    if command in ("add", "add-league"):
        if league_command:
            # The ESPN slug identifies a league even when its display name changes.
            mine = [i for i in items if str(i.get("league", "")).casefold() == args[1].casefold()]
        if mine:
            mine[0]["league"] = args[1]
            if league_command:
                mine[0]["name"] = args[0]
        elif len(items) >= (_gate.MAX_FOLLOWED_LEAGUES if league_command else MAX_TEAMS):
            return fail(f"the paper follows at most 5 {'leagues' if league_command else 'teams'}; remove one first")
        else:
            items.append({"name" if league_command else "team": args[0], "league": args[1]})
    else:
        if not mine:
            return fail(f"{args[0]!r} is not followed")
        items[:] = [i for i in items if i not in mine]
    config["sports"] = {"configured": bool(followed or leagues), "followed": followed}
    if leagues or league_command or "leagues" in block:
        config["sports"]["leagues"] = leagues
    try:
        failures = validate_preferences(config, draft)
    except _gate.GateError as error:
        return fail(str(error))
    if failures:
        return fail(failures)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    print(_summary(followed + leagues))
    return 0


if __name__ == "__main__":
    sys.exit(main())
