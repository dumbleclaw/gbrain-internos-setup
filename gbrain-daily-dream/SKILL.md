---
name: gbrain-daily-dream
description: "Nightly brain update: convert yesterday's Hermes + Claude Code sessions to corpus, synthesize notable content inline, import into gbrain, report to Slack."
version: 1.0.0
author: Aibus Dumbleclaw
license: MIT
platforms: [linux, macos]
prerequisites:
  commands: [python3, bun]
  scripts:
    - ~/.hermes/scripts/sessions-to-corpus.py
    - path/to/claude-code-sessions-to-corpus.py
  skills: [gbrain-internos-setup]
metadata:
  hermes:
    tags: [gbrain, brain, memory, cron, dream, synthesis, internos]
    related_skills: [gbrain-internos-setup, aibus-os-backup]
  gbrain_version_tested: "0.41.26.1"
---

# gbrain Daily Dream

Automated nightly brain update. Runs as a Hermes Agent cron job — the agent IS the synthesis engine (reads corpus, decides what's notable, writes brain pages inline). No Anthropic API key consumed beyond the cron agent itself.

---

## What this skill does

Each night, after sessions have accumulated:

1. **Convert** — run `sessions-to-corpus.py --date yesterday` and `claude-code-sessions-to-corpus.py --date yesterday`
2. **Assess** — read each new corpus file; if it has substantive content (>200 chars), synthesize inline
3. **Write** — write synthesized brain pages to `/tmp/gbrain-synth/`
4. **Import** — `gbrain import /tmp/gbrain-synth/`
5. **Report** — post summary to Slack (pages added, brain total, key topics)

Silent if: no sessions yesterday, all corpus too sparse, or nothing worth synthesizing.

---

## Synthesis criteria (inline — no sub-agent needed)

When reading a corpus file, write a brain page only if it contains:

- Mel articulates a decision, direction, or explicit instruction
- A system upgrade or config change happened with verifiable outcome
- A meaningful operational pattern or constraint is established

Skip if: pure routine ops, no decision or learning, content already indexed from workspaces import.

**Slug rules:**
- Prefixes: `wiki/personal/reflections/`, `wiki/originals/ideas/`, `dream-cycle-summaries/`
- Format: lowercase alphanumeric and hyphens, slash-separated, no underscores, no file extensions
- Include `YYYY-MM-DD` and a 6-char SHA-256 suffix of the corpus file: `wiki/personal/reflections/YYYY-MM-DD-topic-hash6`

---

## Execution procedure

```bash
YESTERDAY=$(date -d yesterday +%Y-%m-%d 2>/dev/null || date -v-1d +%Y-%m-%d)
CC_CONVERTER="$HOME/.hermes/skills/operations/gbrain-internos-setup/claude-code-sessions-to-corpus.py"

# Step 1a — Hermes sessions (always runs)
python3 ~/.hermes/scripts/sessions-to-corpus.py --date "$YESTERDAY"

# Step 1b — Claude Code sessions (best-effort; skip + flag if converter not installed)
if [ -f "$CC_CONVERTER" ]; then
  python3 "$CC_CONVERTER" --date "$YESTERDAY" --min-size 2000
else
  CC_SESSIONS_SKIPPED=true  # surfaced in Slack report — see below
fi

# Step 2–3 — Synthesis (agent reads corpus files and writes pages inline)
# See synthesis criteria above. Write pages to /tmp/gbrain-synth/<slug>.md

# Step 4 — Import
mkdir -p /tmp/gbrain-synth
OPENAI_API_KEY=$(grep '^OPENAI_API_KEY=' ~/.hermes/.env | cut -d= -f2-) \
GBRAIN_DISABLE_DIRECT_POOL=1 \
~/.bun/bin/gbrain import /tmp/gbrain-synth/

# Step 5 — Stats for report
OPENAI_API_KEY=$(grep '^OPENAI_API_KEY=' ~/.hermes/.env | cut -d= -f2-) \
GBRAIN_DISABLE_DIRECT_POOL=1 \
~/.bun/bin/gbrain stats
```

---

## Corpus file locations

After conversion, corpus files land at:

| Source | Path |
|--------|------|
| Hermes sessions | `~/.hermes/gbrain-notes/corpus/YYYY-MM-DD.md` |
| Claude Code sessions | `~/.hermes/gbrain-notes/corpus/claude-code-sessions/YYYY-MM-DD/<id>.md` |

Read each file. Get its SHA-256 hash (first 6 chars) for slug construction:
```bash
sha256sum ~/.hermes/gbrain-notes/corpus/YYYY-MM-DD.md | cut -c1-6
```

---

## Slack report format

Post to origin thread (or Slack home channel) after import:

```
gbrain dream — YYYY-MM-DD

Pages added: N  (brain total: T)
Topics: [one-line summary of what was synthesized, or "nothing notable"]
```

If the CC sessions converter was not found, append:

```
⚠️ CC sessions skipped — converter not installed.
Update: cd ~/.hermes/skills/operations/gbrain-internos-setup && git pull origin main
```

If nothing was written and nothing was imported: stay silent (no post needed).

---

## Cron schedule

Recommended: **5:00am UTC-6** (`0 11 * * *` UTC) — 70 minutes after the aibus-os backup at 3:50am UTC-6, so the brain update always runs on a fresh backup.

Register via Hermes cronjob tool:
```
name: gbrain daily dream
schedule: 0 11 * * *
skill: gbrain-daily-dream
deliver: slack  (aibus-home channel)
no_agent: false
```

---

## Large corpus handling

If yesterday's corpus exceeds ~100KB (heavy session day): pre-summarize before synthesizing. Scan session headers (`grep "^## Session"`), read 20–30 lines per session, build a ~2KB summary, synthesize from that. See `gbrain-internos-setup` skill for the full pattern.

---

## Env pattern

```bash
OPENAI_API_KEY=$(grep '^OPENAI_API_KEY=' ~/.hermes/.env | cut -d= -f2-) \
GBRAIN_DISABLE_DIRECT_POOL=1 \
~/.bun/bin/gbrain <command>
```

Do NOT use `source ~/.env` — fails silently in bash subshells.
