"""Shared helpers for tests that run the real CLI on notes/ (ingest, list, followup)."""

from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

from actiontrack.cli import app

ROOT = Path(__file__).parent.parent
NOTES = ROOT / "notes"
TODAY = "2026-10-22"
runner = CliRunner()


def ingest(db: Path, folder: Path = NOTES, *extra: str):
    return runner.invoke(app, ["ingest", str(folder), "--db", str(db), *extra])


def lst(db: Path, *args: str, today: str = TODAY):
    return runner.invoke(app, ["list", "--db", str(db), "--today", today, *args])


def summary_numbers(out: str) -> dict[str, int]:
    """Parse the counts out of the summary text."""
    d: dict[str, int] = {}
    m = re.search(r"Scanned (\d+) files", out)
    d["scanned"] = int(m[1])
    d["ingested"] = int(re.search(r"Ingested:\s+(\d+)", out)[1])
    d["skipped"] = int(re.search(r"Skipped:\s+(\d+)", out)[1])
    m = re.search(r"Items:\s+(\d+) found -> (\d+) unique \((\d+) duplicates merged\)", out)
    d["found"], d["unique"], d["merged"] = int(m[1]), int(m[2]), int(m[3])
    m = re.search(r"new (\d+), updated (\d+), unchanged (\d+)", out)
    d["new"], d["updated"], d["unchanged"] = int(m[1]), int(m[2]), int(m[3])
    return d


def skipped_section(out: str) -> dict[str, str]:
    """{file: reason} from the 'Skipped files:' block."""
    result: dict[str, str] = {}
    if "Skipped files:" not in out:
        return result
    block = out.split("Skipped files:")[1].split("\n\n")[0]
    for line in block.strip().splitlines():
        name, _, reason = line.strip().partition("  ")
        result[name] = reason.strip()
    return result


def rows(out: str) -> list[list[str]]:
    """List-table rows split on 2+ spaces (header and footer dropped)."""
    lines = out.strip().splitlines()[1:-1]
    return [re.split(r"\s{2,}", ln.strip()) for ln in lines]
