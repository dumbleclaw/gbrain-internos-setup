#!/usr/bin/env python3
"""
sessions-to-corpus.py — Convert Hermes JSONL session files to gbrain corpus markdown.

Reads ~/.hermes/sessions/YYYYMMDD_*.jsonl, extracts user + assistant turns,
and writes dated .md files to the gbrain corpus directory.

Usage:
    python3 sessions-to-corpus.py --date 2026-05-27
    python3 sessions-to-corpus.py --from 2026-05-14 --to 2026-05-27
    python3 sessions-to-corpus.py --date 2026-05-27 --dry-run
    python3 sessions-to-corpus.py --date 2026-05-27 --force

Environment:
    HERMES_HOME        Path to .hermes dir (default: ~/.hermes)
    GBRAIN_CORPUS_DIR  Override corpus output dir (default: read from gbrain config)

Config:
    Corpus dir is read from gbrain config key dream.synthesize.session_corpus_dir.
    Override with GBRAIN_CORPUS_DIR env var if gbrain is not available.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path


HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
SESSIONS_DIR = HERMES_HOME / "sessions"

SKIP_PREFIXES = (
    "[CONTEXT COMPACTION",
    "[SYSTEM",
    "[Thread context",
    "[thread context",
)

REPLY_PREFIX_RE = re.compile(r"^\[Replying to:.*?\]\s*\n\n", re.DOTALL)
SPEAKER_RE = re.compile(r"^\[(?:mel|Mel|MEL)\]\s*", re.IGNORECASE)


def get_corpus_dir() -> Path:
    env_override = os.environ.get("GBRAIN_CORPUS_DIR")
    if env_override:
        return Path(env_override)

    gbrain = Path.home() / ".bun" / "bin" / "gbrain"
    if not gbrain.exists():
        sys.exit("gbrain not found at ~/.bun/bin/gbrain. Set GBRAIN_CORPUS_DIR env var to override.")

    env = {
        **os.environ,
        "GBRAIN_DISABLE_DIRECT_POOL": "1",
    }
    result = subprocess.run(
        [str(gbrain), "config", "get", "dream.synthesize.session_corpus_dir"],
        capture_output=True, text=True, env=env,
    )
    for line in result.stdout.splitlines():
        line = line.strip()
        if line and not line.startswith("[gbrain]"):
            return Path(line)

    sys.exit(
        "dream.synthesize.session_corpus_dir not set in gbrain config.\n"
        "Run: gbrain config set dream.synthesize.session_corpus_dir <path>\n"
        "Or set GBRAIN_CORPUS_DIR env var."
    )


def parse_date_range(args) -> list[date]:
    if args.date:
        d = datetime.strptime(args.date, "%Y-%m-%d").date()
        return [d]
    if args.from_date and args.to_date:
        start = datetime.strptime(args.from_date, "%Y-%m-%d").date()
        end = datetime.strptime(args.to_date, "%Y-%m-%d").date()
        if start > end:
            sys.exit("--from date must be before --to date")
        days = []
        cur = start
        while cur <= end:
            days.append(cur)
            cur += timedelta(days=1)
        return days
    sys.exit("Provide --date or both --from and --to")


def sessions_for_date(day: date) -> list[Path]:
    prefix = day.strftime("%Y%m%d")
    files = sorted(SESSIONS_DIR.glob(f"{prefix}_*.jsonl"))
    return files


def clean_user_content(text: str) -> str:
    # Strip [Replying to: "..."] thread context block
    text = REPLY_PREFIX_RE.sub("", text)
    # Strip [mel] / [Mel] speaker tag — we add our own label
    text = SPEAKER_RE.sub("", text)
    return text.strip()


def extract_turns(path: Path) -> list[dict]:
    """Extract meaningful user + assistant turns from a session JSONL file."""
    turns = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            role = obj.get("role", "")
            if role not in ("user", "assistant"):
                continue

            content = obj.get("content", "")
            if not isinstance(content, str):
                continue
            content = content.strip()
            if not content:
                continue

            timestamp = obj.get("timestamp", "")

            if role == "user":
                content = clean_user_content(content)
                if not content:
                    continue
                # Check skip prefixes after cleaning (reply prefix stripped first)
                if any(content.startswith(p) for p in SKIP_PREFIXES):
                    continue
                turns.append({"role": "Mel", "content": content, "timestamp": timestamp})
            else:
                # Check skip prefixes on raw assistant content
                if any(content.startswith(p) for p in SKIP_PREFIXES):
                    continue
                turns.append({"role": "Aibus", "content": content, "timestamp": timestamp})

    return turns


def format_corpus_doc(day: date, sessions: list[tuple[Path, list[dict]]]) -> str:
    lines = [
        f"# Session transcript — {day.strftime('%Y-%m-%d')}",
        "",
        f"Source: {len(sessions)} session(s) from Hermes operational log.",
        f"Imported: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "",
    ]

    written = 0
    for path, turns in sessions:
        if not turns:
            continue
        written += 1
        session_id = path.stem
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"## Session {written} — `{session_id}`")
        lines.append("")

        for turn in turns:
            ts = f" _{turn['timestamp']}_" if turn.get("timestamp") else ""
            lines.append(f"**{turn['role']}**{ts}")
            lines.append("")
            lines.append(turn["content"])
            lines.append("")

    return "\n".join(lines)


def convert_day(day: date, corpus_dir: Path, dry_run: bool, force: bool) -> dict:
    out_path = corpus_dir / f"{day.strftime('%Y-%m-%d')}.md"
    session_files = sessions_for_date(day)

    result = {
        "date": str(day),
        "sessions": len(session_files),
        "output": str(out_path),
        "skipped": False,
        "dry_run": dry_run,
        "turns": 0,
        "error": None,
    }

    if not session_files:
        result["skipped"] = True
        result["reason"] = "no session files for this date"
        return result

    if out_path.exists() and not force:
        result["skipped"] = True
        result["reason"] = "corpus file already exists (use --force to overwrite)"
        return result

    sessions_data = []
    total_turns = 0
    for path in session_files:
        turns = extract_turns(path)
        sessions_data.append((path, turns))
        total_turns += len(turns)

    result["turns"] = total_turns

    if total_turns == 0:
        result["skipped"] = True
        result["reason"] = "all sessions empty after filtering"
        return result

    doc = format_corpus_doc(day, sessions_data)

    if not dry_run:
        corpus_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(doc, encoding="utf-8")

    return result


def main():
    parser = argparse.ArgumentParser(description="Convert Hermes sessions to gbrain corpus markdown.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--date", metavar="YYYY-MM-DD", help="Convert a single date")
    group.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD", help="Start of date range")
    parser.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD", help="End of date range (required with --from)")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report without writing files")
    parser.add_argument("--force", action="store_true", help="Overwrite existing corpus files")
    parser.add_argument("--corpus-dir", metavar="PATH", help="Override corpus output directory")
    args = parser.parse_args()

    if args.from_date and not args.to_date:
        parser.error("--from requires --to")

    corpus_dir = Path(args.corpus_dir) if args.corpus_dir else get_corpus_dir()
    days = parse_date_range(args)

    print(f"Corpus dir : {corpus_dir}")
    print(f"Dates      : {days[0]} → {days[-1]} ({len(days)} day(s))")
    print(f"Dry run    : {args.dry_run}")
    print()

    total_written = 0
    total_skipped = 0
    total_turns = 0

    for day in days:
        r = convert_day(day, corpus_dir, dry_run=args.dry_run, force=args.force)
        if r["skipped"]:
            print(f"  SKIP  {r['date']} — {r.get('reason', '')}")
            total_skipped += 1
        elif r["error"]:
            print(f"  ERROR {r['date']} — {r['error']}")
        else:
            action = "DRY-RUN" if args.dry_run else "WROTE"
            print(f"  {action} {r['date']} — {r['sessions']} session(s), {r['turns']} turns → {r['output']}")
            total_written += 1
            total_turns += r["turns"]

    print()
    print(f"Done. Written: {total_written}, Skipped: {total_skipped}, Total turns: {total_turns}")


if __name__ == "__main__":
    main()
