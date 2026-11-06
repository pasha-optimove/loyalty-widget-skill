#!/usr/bin/env node
import { createServer } from 'node:http';
import { readFileSync, statSync } from 'node:fs';
import { resolve, basename } from 'node:path';
import { parseArgs } from 'node:util';
import { randomBytes } from 'node:crypto';

const PAGE_KEYS = ['dashboard', 'levels', 'missions', 'tournaments', 'badges', 'store', 'lootboxes', 'profile'];
const PROD_REGIONS = ['eu', 'us'];
const PRE_PROD_REGIONS = ['dev', 'qa', 'staging'];

function apiUrl(region) {
  return `https://opti-ls-api-${PRE_PROD_REGIONS.includes(region) ? 'qa' : region}.optimove.net/api`;
}

function regions(first) {
  const start = first.toLowerCase();
  if (PRE_PROD_REGIONS.includes(start)) return [start];
  return [...new Set([start, ...PROD_REGIONS])];
}

async function findTenant(tenant, firstRegion) {
  const path = `/brands/default/${encodeURIComponent(tenant)}`;
  const unreachable = [];
  for (const region of regions(firstRegion)) {
    const url = apiUrl(region) + path;
    try {
      const res = await fetch(url, { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(15000) });
      if (res.status === 404) continue;
      if (!res.ok) {
        unreachable.push(`${url} answered ${res.status}`);
        continue;
      }
      const found = await res.json();
      if (found && found.id) return region;
    } catch (e) {
      unreachable.push(`${apiUrl(region)} unreachable (${e.cause?.code || e.name})`);
    }
  }
  if (unreachable.length) {
    console.error(`warning: could not confirm the tenant: ${unreachable.join('; ')}`);
    return 'unknown';
  }
  return null;
}

function fail(message) {
  console.error(message);
  process.exit(1);
}

let parsed;
try {
  parsed = parseArgs({
    allowPositionals: true,
    options: {
      port: { type: 'string', default: '8766' },
      tenant: { type: 'string' },
      region: { type: 'string', default: 'eu' },
    },
  });
} catch (e) {
  fail(`${e.message}\nusage: node serve.mjs <skin.html> [--port 8766] [--tenant <id>] [--region eu]`);
}
const { values, positionals } = parsed;

if (positionals.length !== 1) fail('usage: node serve.mjs <skin.html> [--port 8766] [--tenant <id>] [--region eu]');
const skin = resolve(positionals[0]);
try {
  if (!statSync(skin).isFile()) throw new Error();
} catch {
  fail(`${skin} does not exist; build it first`);
}

const port = Number(values.port);
const base = `http://localhost:${port}`;
if (values.tenant !== undefined) {
  if (!/^\d+$/.test(values.tenant)) fail(`tenant id must be a number, got '${values.tenant}'`);
  const region = await findTenant(values.tenant, values.region);
  if (!region) fail(`tenant ${values.tenant} was not found in any region; check the tenant id`);
  const player = `player-${randomBytes(3).toString('hex')}`;
  const prefix = `/${values.tenant}/${player}`;
  console.log(`tenant    ${values.tenant} (default brand, region ${region})`);
  console.log(`player    ${player} (random, so it has no progress)`);
  console.log(`open      ${base}${prefix}/${PAGE_KEYS[0]}`);
  console.log(`pages     ${PAGE_KEYS.slice(1).map((p) => `${base}${prefix}/${p}`).join('  ')}`);
} else {
  console.log(`serving ${basename(skin)} at ${base}/<tenantId>/<playerId>/<page>`);
}

const server = createServer((req, res) => {
  const body = readFileSync(skin);
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', 'Content-Length': body.length });
  res.end(body);
});
server.on('error', (e) => {
  if (e.code === 'EADDRINUSE') fail(`port ${port} is already in use; pass --port with a free one, or stop what runs there`);
  throw e;
});
server.listen(port, '127.0.0.1', () => console.log(`serving   ${skin} (stop with Ctrl+C)`));
