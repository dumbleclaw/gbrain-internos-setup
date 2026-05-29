#!/usr/bin/env bun
/**
 * gbrain-prejudge.ts — Pre-populate gbrain's dream_verdicts cache.
 *
 * Reads corpus .md files, hashes them (SHA-256, matching gbrain's logic),
 * and inserts verdict rows into Supabase so gbrain's dream synthesize phase
 * uses cached verdicts instead of calling the Haiku significance judge.
 *
 * Usage:
 *   bun run gbrain-prejudge.ts --date 2026-05-24
 *   bun run gbrain-prejudge.ts --from 2026-05-14 --to 2026-05-27
 *   bun run gbrain-prejudge.ts --date 2026-05-24 --worth false   (mark as not worth)
 *   bun run gbrain-prejudge.ts --date 2026-05-24 --dry-run
 *
 * The script reads DATABASE_URL from ~/.gbrain/config.json.
 * Set GBRAIN_DISABLE_DIRECT_POOL=1 to avoid IPv6 issues (same as gbrain itself).
 */

import { createHash } from "crypto";
import { readFileSync, readdirSync, existsSync } from "fs";
import { join, basename } from "path";
import { homedir } from "os";
import postgres from "postgres";

const CORPUS_DIR = join(homedir(), ".hermes/gbrain-notes/corpus");
const DATE_RE = /^(\d{4}-\d{2}-\d{2})/;

function hashContent(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

function parseArgs() {
  const args = process.argv.slice(2);
  const get = (flag: string) => {
    const i = args.indexOf(flag);
    return i !== -1 ? args[i + 1] : null;
  };
  return {
    date: get("--date"),
    from: get("--from"),
    to: get("--to"),
    worth: get("--worth") !== "false",
    dryRun: args.includes("--dry-run"),
    corpusDir: get("--corpus-dir") ?? CORPUS_DIR,
  };
}

function datesInRange(from: string, to: string): string[] {
  const dates: string[] = [];
  const cur = new Date(from + "T00:00:00Z");
  const end = new Date(to + "T00:00:00Z");
  while (cur <= end) {
    dates.push(cur.toISOString().slice(0, 10));
    cur.setUTCDate(cur.getUTCDate() + 1);
  }
  return dates;
}

function corpusFilesForDates(corpusDir: string, dates: string[]): string[] {
  const dateSet = new Set(dates);
  if (!existsSync(corpusDir)) return [];
  return readdirSync(corpusDir)
    .filter((name) => {
      if (!name.endsWith(".md") && !name.endsWith(".txt")) return false;
      const base = basename(name, name.endsWith(".md") ? ".md" : ".txt");
      const m = DATE_RE.exec(base);
      return m && dateSet.has(m[1]);
    })
    .map((name) => join(corpusDir, name))
    .sort();
}

function loadConfig(): { database_url: string } {
  const cfgPath = join(homedir(), ".gbrain/config.json");
  return JSON.parse(readFileSync(cfgPath, "utf8"));
}

function patchUrl(url: string): string {
  if (process.env.GBRAIN_DISABLE_DIRECT_POOL === "1") {
    // Force session pooler port 6543 if direct connection was somehow embedded
    return url.replace(/:5432\//, ":6543/");
  }
  return url;
}

async function main() {
  const opts = parseArgs();

  // Resolve date range
  let dates: string[];
  if (opts.date) {
    dates = [opts.date];
  } else if (opts.from && opts.to) {
    dates = datesInRange(opts.from, opts.to);
  } else {
    console.error("Provide --date or --from + --to");
    process.exit(1);
  }

  const files = corpusFilesForDates(opts.corpusDir, dates);
  if (files.length === 0) {
    console.log(`No corpus files found for dates: ${dates.join(", ")}`);
    process.exit(0);
  }

  console.log(`Corpus dir : ${opts.corpusDir}`);
  console.log(`Dates      : ${dates[0]} → ${dates[dates.length - 1]}`);
  console.log(`Files      : ${files.length}`);
  console.log(`Worth      : ${opts.worth}`);
  console.log(`Dry run    : ${opts.dryRun}`);
  console.log();

  const cfg = loadConfig();
  const dbUrl = patchUrl(cfg.database_url);

  const sql = opts.dryRun ? null : postgres(dbUrl, { prepare: false });

  let written = 0;
  let skipped = 0;

  for (const filePath of files) {
    const content = readFileSync(filePath, "utf8");
    const contentHash = hashContent(content);
    const reasons = opts.worth
      ? ["pre-judged: operational log, worth synthesizing"]
      : ["pre-judged: sparse content, not worth synthesizing"];

    if (opts.dryRun) {
      console.log(`  DRY-RUN  ${basename(filePath)} hash=${contentHash.slice(0, 12)}... worth=${opts.worth}`);
      written++;
      continue;
    }

    try {
      await sql!`
        INSERT INTO dream_verdicts (file_path, content_hash, worth_processing, reasons)
        VALUES (${filePath}, ${contentHash}, ${opts.worth}, ${JSON.stringify(reasons)})
        ON CONFLICT (file_path, content_hash) DO UPDATE SET
          worth_processing = EXCLUDED.worth_processing,
          reasons          = EXCLUDED.reasons,
          judged_at        = now()
      `;
      console.log(`  WROTE    ${basename(filePath)} hash=${contentHash.slice(0, 12)}... worth=${opts.worth}`);
      written++;
    } catch (e: any) {
      console.error(`  ERROR    ${basename(filePath)}: ${e.message}`);
      skipped++;
    }
  }

  if (sql) await sql.end();

  console.log();
  console.log(`Done. Written: ${written}, Errors: ${skipped}`);
}

main().catch((e) => { console.error(e); process.exit(1); });
