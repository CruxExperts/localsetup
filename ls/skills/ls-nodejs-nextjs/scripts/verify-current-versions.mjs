#!/usr/bin/env node

import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SOURCES = {
  next: "https://registry.npmjs.org/next",
  react: "https://registry.npmjs.org/react",
  reactDom: "https://registry.npmjs.org/react-dom",
  nodeSchedule: "https://raw.githubusercontent.com/nodejs/Release/main/schedule.json",
  nodeDistIndex: "https://nodejs.org/dist/index.json",
};

const REQUIRED_NODE_LINES = ["20", "22", "24", "25", "26"];
const FETCH_TIMEOUT_MS = 15000;

function usage() {
  return `Usage: node scripts/verify-current-versions.mjs [--json] [--help]

Fetch current primary-source metadata for Next.js, React, React DOM, and Node.js.

Options:
  --json    Print machine-readable JSON.
  --help    Show this help text.

The script is read-only. It performs no installs, makes no dependency changes,
and does not rewrite data/verified-versions.json.`;
}

function parseArgs(argv) {
  const options = { json: false, help: false };
  for (const arg of argv) {
    if (arg === "--json") {
      options.json = true;
    } else if (arg === "--help" || arg === "-h") {
      options.help = true;
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  return options;
}

async function fetchJson(url, label) {
  let response;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    response = await fetch(url, {
      signal: controller.signal,
      headers: {
        accept: "application/json",
        "user-agent": "localsetup-ls-nodejs-nextjs-verifier/1.0",
      },
    });
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error(`Timed out fetching ${label} from ${url} after ${FETCH_TIMEOUT_MS}ms`);
    }
    throw new Error(`Failed to fetch ${label} from ${url}: ${error.message}`);
  } finally {
    clearTimeout(timeout);
  }

  if (!response.ok) {
    throw new Error(`Failed to fetch ${label} from ${url}: HTTP ${response.status}`);
  }

  try {
    return await response.json();
  } catch (error) {
    throw new Error(`Invalid JSON for ${label} from ${url}: ${error.message}`);
  }
}

function assertObject(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`Expected ${label} to be an object`);
  }
}

function assertString(value, label) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`Expected ${label} to be a non-empty string`);
  }
}

function packageSnapshot(name, metadata, extra = {}) {
  assertObject(metadata, `${name} metadata`);
  assertObject(metadata["dist-tags"], `${name} dist-tags`);
  const latest = metadata["dist-tags"].latest;
  assertString(latest, `${name} dist-tags.latest`);
  const latestVersion = metadata.versions?.[latest];
  assertObject(latestVersion, `${name}@${latest} package metadata`);

  return {
    latest,
    distTags: metadata["dist-tags"],
    engines: latestVersion.engines || {},
    peerDependencies: latestVersion.peerDependencies || {},
    ...extra,
  };
}

function latestDistByLine(distIndex) {
  if (!Array.isArray(distIndex)) {
    throw new Error("Expected Node dist index to be an array");
  }
  const latest = {};
  for (const entry of distIndex) {
    if (!entry || typeof entry.version !== "string") {
      continue;
    }
    const match = /^v(\d+)\./.exec(entry.version);
    if (!match) {
      continue;
    }
    const line = match[1];
    if (!latest[line]) {
      latest[line] = {
        version: entry.version,
        date: entry.date,
        lts: entry.lts,
        security: Boolean(entry.security),
      };
    }
  }
  return latest;
}

function statusForLine(line, scheduleEntry, now) {
  const start = Date.parse(scheduleEntry.start);
  const lts = scheduleEntry.lts ? Date.parse(scheduleEntry.lts) : null;
  const maintenance = scheduleEntry.maintenance ? Date.parse(scheduleEntry.maintenance) : null;
  const end = Date.parse(scheduleEntry.end);

  if (Number.isFinite(end) && now > end) {
    return "EOL";
  }
  if (lts && maintenance && now >= maintenance) {
    return "Maintenance LTS";
  }
  if (lts && now >= lts) {
    return "Active LTS";
  }
  if (Number.isFinite(start) && now >= start) {
    return "Current";
  }
  return `Future (${line}.x)`;
}

function nodeSnapshot(schedule, distIndex) {
  assertObject(schedule, "Node release schedule");
  const latestByLine = latestDistByLine(distIndex);
  const now = Date.now();
  const releaseLines = {};

  for (const line of REQUIRED_NODE_LINES) {
    const key = `v${line}`;
    const entry = schedule[key];
    assertObject(entry, `Node schedule ${key}`);
    const latestDist = latestByLine[line];
    assertObject(latestDist, `latest Node dist entry for ${key}`);
    releaseLines[line] = {
      scheduleKey: key,
      codename: entry.codename ?? null,
      status: statusForLine(line, entry, now),
      start: entry.start,
      lts: entry.lts,
      maintenance: entry.maintenance,
      end: entry.end,
      latestDist: latestDist.version,
      latestDistDate: latestDist.date,
      latestDistLts: latestDist.lts,
      latestDistSecurity: latestDist.security,
    };
  }

  return { releaseLines };
}

async function readStoredSnapshot() {
  const here = dirname(fileURLToPath(import.meta.url));
  const path = resolve(here, "../data/verified-versions.json");
  try {
    const raw = await readFile(path, "utf8");
    return JSON.parse(raw);
  } catch (error) {
    if (error.code === "ENOENT") {
      return null;
    }
    throw new Error(`Failed to read stored snapshot ${path}: ${error.message}`);
  }
}

function compareSnapshots(current, stored) {
  if (!stored) {
    return [{ path: "data/verified-versions.json", before: null, after: "missing" }];
  }

  const valueAt = (object, path) =>
    path.split(".").reduce((value, part) => (value == null ? undefined : value[part]), object);

  const checks = [
    "packages.next.latest",
    "packages.next.distTags.latest",
    "packages.next.distTags.canary",
    "packages.next.distTags.beta",
    "packages.next.distTags.rc",
    "packages.next.engines",
    "packages.next.peerDependencies",
    "packages.react.latest",
    "packages.react.distTags.latest",
    "packages.react.distTags.canary",
    "packages.react.distTags.experimental",
    "packages.react.distTags.next",
    "packages.react.engines",
    "packages.react-dom.latest",
    "packages.react-dom.distTags.latest",
    "packages.react-dom.distTags.canary",
    "packages.react-dom.distTags.experimental",
    "packages.react-dom.distTags.next",
    "packages.react-dom.peerDependencies",
  ];

  for (const line of REQUIRED_NODE_LINES) {
    checks.push(
      `node.releaseLines.${line}.status`,
      `node.releaseLines.${line}.start`,
      `node.releaseLines.${line}.lts`,
      `node.releaseLines.${line}.maintenance`,
      `node.releaseLines.${line}.end`,
      `node.releaseLines.${line}.latestDist`,
      `node.releaseLines.${line}.latestDistDate`,
      `node.releaseLines.${line}.latestDistLts`
    );
  }

  return checks
    .map((path) => [path, valueAt(current, path), valueAt(stored, path)])
    .filter(([, currentValue, storedValue]) => JSON.stringify(currentValue ?? null) !== JSON.stringify(storedValue ?? null))
    .map(([path, currentValue, storedValue]) => ({ path, before: storedValue ?? null, after: currentValue ?? null }));
}

async function buildSnapshot() {
  const [nextMeta, reactMeta, reactDomMeta, schedule, distIndex] = await Promise.all([
    fetchJson(SOURCES.next, "next npm metadata"),
    fetchJson(SOURCES.react, "react npm metadata"),
    fetchJson(SOURCES.reactDom, "react-dom npm metadata"),
    fetchJson(SOURCES.nodeSchedule, "Node release schedule"),
    fetchJson(SOURCES.nodeDistIndex, "Node dist index"),
  ]);

  const current = {
    verifiedAt: new Date().toISOString(),
    sources: SOURCES,
    packages: {
      next: packageSnapshot("next", nextMeta),
      react: packageSnapshot("react", reactMeta),
      "react-dom": packageSnapshot("react-dom", reactDomMeta),
    },
    node: nodeSnapshot(schedule, distIndex),
  };

  const stored = await readStoredSnapshot();
  current.drift = compareSnapshots(current, stored);
  return current;
}

function printHuman(snapshot) {
  const lines = [];
  lines.push(`Verified at: ${snapshot.verifiedAt}`);
  lines.push("");
  lines.push("Packages:");
  lines.push(`  next latest: ${snapshot.packages.next.latest}`);
  lines.push(`    canary: ${snapshot.packages.next.distTags.canary ?? "n/a"}`);
  lines.push(`    beta: ${snapshot.packages.next.distTags.beta ?? "n/a"}`);
  lines.push(`    rc: ${snapshot.packages.next.distTags.rc ?? "n/a"}`);
  lines.push(`    engines.node: ${snapshot.packages.next.engines.node ?? "n/a"}`);
  lines.push(`    peer react: ${snapshot.packages.next.peerDependencies.react ?? "n/a"}`);
  lines.push(`    peer react-dom: ${snapshot.packages.next.peerDependencies["react-dom"] ?? "n/a"}`);
  lines.push(`  react latest: ${snapshot.packages.react.latest}`);
  lines.push(`  react-dom latest: ${snapshot.packages["react-dom"].latest}`);
  lines.push(`    peer react: ${snapshot.packages["react-dom"].peerDependencies.react ?? "n/a"}`);
  lines.push("");
  lines.push("Node release lines:");
  for (const line of REQUIRED_NODE_LINES) {
    const entry = snapshot.node.releaseLines[line];
    lines.push(`  ${line}.x: ${entry.status}; latest ${entry.latestDist}; end ${entry.end}`);
  }
  lines.push("");
  if (snapshot.drift.length === 0) {
    lines.push("Stored snapshot drift: none for checked fields.");
  } else {
    lines.push("Stored snapshot drift:");
    for (const item of snapshot.drift) {
      lines.push(`  ${item.path}: stored=${item.before ?? "null"} current=${item.after ?? "null"}`);
    }
  }
  console.log(lines.join("\n"));
}

async function main() {
  let options;
  try {
    options = parseArgs(process.argv.slice(2));
  } catch (error) {
    console.error(error.message);
    console.error(usage());
    process.exitCode = 2;
    return;
  }

  if (options.help) {
    console.log(usage());
    return;
  }

  try {
    const snapshot = await buildSnapshot();
    if (options.json) {
      console.log(JSON.stringify(snapshot, null, 2));
    } else {
      printHuman(snapshot);
    }
  } catch (error) {
    console.error(`verify-current-versions: ${error.message}`);
    process.exitCode = 1;
  }
}

await main();
