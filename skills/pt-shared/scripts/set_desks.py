#!/usr/bin/env python3
"""Opt into newspaper departments: set_desks.py <weather|calendar|mail> <on|off>.

Missing switches mean off. Validates before an
atomic replacement; never restarts onboarding to change a department.
"""
from __future__ import annotations

import json
import os
import sys

import pt_config_gate
from pt_paths import config_file


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2 or argv[0] not in ("weather", "calendar", "mail") or argv[1] not in ("on", "off"):
        print("error: usage: set_desks.py <weather|calendar|mail> <on|off>", file=sys.stderr)
        return 1
    path = config_file()
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("not a JSON object")
        config[argv[0]] = {"configured": argv[1] == "on"}
        failures = pt_config_gate.gate(config)
        if failures:
            raise ValueError(failures)
    except (OSError, ValueError, pt_config_gate.GateError) as error:
        print(f"error: could not change department: {error}", file=sys.stderr)
        return 1
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    print(f"DESK:{argv[0]}:{argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
