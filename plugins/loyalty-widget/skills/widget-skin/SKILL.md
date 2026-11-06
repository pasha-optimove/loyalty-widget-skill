---
name: widget-skin
description: Design and build a fully custom gamify (opti-ls) loyalty widget skin — dashboard, levels, missions, tournaments, badges, store, lootboxes and profile — from a brand's website, its source code, code pasted into the chat, or a brandbook, as one self-contained HTML file. Brand tokens are read from pasted code, over HTTP or from local files, without opening a browser. Pages are written as local fragments, checked against the page contract, assembled with the bundled GamifySDK, and checked in a browser on desktop and phone when a browser tool is available. Use when asked to create, skin, theme, restyle or iterate on a loyalty widget, rewards hub or gamify UI for a brand, e.g. "build a loyalty widget from our website", "make the missions page look better", "skin the widget in our brandbook", "here is our CSS, build the widget from it".
---

# Widget skin

Build the player-facing loyalty widget in any visual style while every feature keeps working. You write HTML/CSS/JS fragments in a local folder. `scripts/build.py` checks them against the page contract and assembles one self-contained file with GamifySDK injected. Edits are local: change one file, rebuild, reload.

Everything it needs ships with the skill: `scripts/skin.py` (page contract, sample data, assembler), `scripts/gamify-sdk.js` (the SDK every skin runs on), and `brand.py`, `serve.py` and `verify.js`. Python 3.9 or newer with no extra packages is enough. The Optimove MCP's `builder(action='create_widget_skin')` uses the same contract and SDK, so a skin that builds here builds there.

`<skill dir>` below is this skill's base directory, shown when the skill loads.

**Read `reference/spec.md` before writing any page.** It is the spec: page contract, hard rules, the full GamifySDK reference and every `state` shape. This file covers the workflow.

## 1. Pull the brand

Read the brand from its source with `brand.py`. No browser is needed for any of these:

```bash
python3 <skill dir>/scripts/brand.py <source>
```

| Source | `<source>` | What it reads |
|---|---|---|
| Code the user pasted into the chat | `-`, with the paste on stdin | Anything, mixed freely: a page's HTML source, CSS, SCSS, a Tailwind config, design-token JSON, a theme object. HTML is parsed, `<style>` blocks and raw CSS are read as CSS, and colors written anywhere else count too |
| A website URL | the URL | The page's HTML, every stylesheet it links or imports, inline styles and Google Fonts links, over plain HTTP |
| A local folder | the path | A site repo, theme or design-token package: CSS/SCSS/LESS, HTML and templates, components (`.tsx`, `.vue`, `.svelte`…), Tailwind config and `theme`/`tokens`/`colors` files. `node_modules`, `dist` and `build` are skipped |
| A single file | the path | One stylesheet, token file or exported brandbook page |

For pasted code, write the paste to a file exactly as given, byte for byte, then pipe it in. This avoids shell quoting:

```bash
python3 <skill dir>/scripts/brand.py - < <project>/brand-source.txt
```

It prints JSON: CSS variables (`:root` first), colors ranked overall and by role (background, text, border, `/0.35` marks alpha), fonts (Google Fonts, `@font-face`, used in CSS, used on headings), corner radii, shadows, logo, icon and image URLs, the headings and menu/button labels for the brand's voice, and `themeFiles` with the raw excerpt of any Tailwind config or token file, so you can see what each color is called (`primary`, `accent`, `surface`). Behind a corporate proxy, set `SSL_CERT_FILE` to a bundle that includes the proxy's certificate for URLs.

From a brandbook PDF or images, read colors, type, radius, imagery and tone of voice from it directly.

**When `warnings` says there is almost no styling**, the site builds its look with JavaScript at runtime. Ask the user to paste one of these instead, in this order:

1. The site's CSS files, or its design tokens / Tailwind / theme config, if they have the code.
2. The rendered page: in their own browser, open developer tools, right-click `<html>` in Elements, choose Copy > Copy outerHTML, and paste it.
3. A brandbook, or the brand's main colors and fonts in words.

Open a browser yourself only if a browser tool (chrome-devtools) is available and the user hasn't said not to. Then read the computed tokens:

```js
() => {
  const vars = {};
  for (const s of document.styleSheets) { try { for (const r of s.cssRules) if (r.selectorText === ':root') for (const p of r.style) vars[p] = r.style.getPropertyValue(p).trim(); } catch (e) {} }
  const pick = (sel) => { const el = document.querySelector(sel); if (!el) return null; const c = getComputedStyle(el); return { font: c.fontFamily, size: c.fontSize, weight: c.fontWeight, color: c.color, bg: c.backgroundColor, border: c.border, radius: c.borderRadius }; };
  return { vars, fonts: [...document.querySelectorAll('link[href*="fonts.googleapis"]')].map((l) => l.href), body: pick('body'), h2: pick('h2'), button: pick('button, .btn, a[class*="btn"]'), card: pick('[class*="card"]') };
}
```

Either way, turn the tokens into a design: note signature details such as dividers, numbering, labels, paper panels and how buttons are shaped. Write the brand's voice into every label and empty state. A skin that only swaps colors is not done.

## 2. Write the project folder

Use the scratchpad unless the user names a place. One file per part:

```
<project>/
  styles.css        shared tokens and components; only a Google Fonts @import is allowed
  shell.html        header, navigation, one element with data-gamify-outlet, shared helpers
  dashboard.html    levels.html  missions.html  tournaments.html
  badges.html       store.html   lootboxes.html profile.html
```

Each page is a fragment (markup plus optional `<style>` and `<script>`) that calls `GamifySDK.definePage('<page>', fn)`. Put helpers every page needs (escape, number format, icon with fallback, toast, act-with-disable) in one `window.<prefix>` object in `shell.html`.

Layout rules that past skins broke:

| Rule | Why |
|---|---|
| Grid columns are `minmax(0,1fr)`, never `1fr`, and flex/grid children get `min-width:0` | A scrolling nav or long name inside a `1fr` column made the whole page 1187px wide on a phone |
| Horizontal nav scrolls inside its own `overflow-x:auto` box | Eight tabs never fit at 390px |
| Lists sort by what the player can act on first: ready, then progress, then locked or done | Players look for what they can collect |
| Reward chips cap at 3 plus "+N" | Some missions carry 6+ rewards |
| Big counts and prices use a face with unambiguous numerals | Some old-style display serifs draw "1" like a Roman "I", which misreads next to numbered labels |

## 3. Get the data

| Need | How |
|---|---|
| Real data for any tenant | No seed needed: step 5 serves the build on the tenant the user names. Add `--region us` to `build.py` when most tenants are in the US; it only changes which region is tried first. |
| Fast first look, offline | No seed. `build.py` invents a sample player and catalog, shown when the file is opened directly. |
| The brand's real catalog with a simulated player, as a file | Needs the Optimove MCP: one `builder(action='create_widget_skin', brand='<brand>')` call with a minimal skin (below). Save its `html` as `<project>/seed.html`. |
| A real player, as a file | The same MCP call with `data_mode='live', customer_id='<test player>'`. Rarely needed: step 5 already shows a tenant's real data. Live actions write to that player's account. |

Minimal skin for the seed call. It passes the contract and keeps the request small:

```json
{"shell": "<main data-gamify-outlet></main>",
 "dashboard": "<div></div><script>GamifySDK.definePage('dashboard', function () {});</script>"}
```

The seed only supplies `window.__GAMIFY__` (mode, catalog, player, live target). Your fragments replace everything else. If the MCP refuses the call, tell the user why and continue without a seed.

## 4. Build

```bash
python3 <skill dir>/scripts/build.py <project> [--seed <project>/seed.html] [--out <file>] [--title "<Brand> Rewards"]
```

`CONTRACT FAILED` lists every problem; fix them all before you rebuild. `MISSING` means players would lose those pages. `DANGLING` names nav links to pages that don't exist.

## 5. Serve on a tenant

Don't hand over instructions for opening the skin: start it yourself.

1. **Ask the user for the tenant id** to preview, if they haven't given one. Only the tenant: the skin uses its default brand and a random player.
2. **Start the server in the background** (it keeps running), with Python, or with Node 18+ when `python3` is missing or fails to start:

   ```bash
   python3 <skill dir>/scripts/serve.py <file>.html --tenant <tenantId> --port 8766
   node <skill dir>/scripts/serve.mjs <file>.html --tenant <tenantId> --port 8766
   ```

   Both check that the tenant exists (EU first, then US; `--region us` flips the order) before serving, pick a random player id, and print the `open` link plus one link per page. The skin at that link reads the tenant's real catalog through the live player APIs; the random player has no progress.
3. **Read the output and act on it:**

   | output | do |
   |---|---|
   | `open http://localhost:…` | Give the user that link. |
   | `tenant … was not found in any region` | Tell the user and ask for the tenant id again. |
   | `port … is already in use` | Run it again with the next port (`--port 8767`). |
   | `warning: could not confirm the tenant` | The opti-ls hosts were unreachable (offline, or a proxy: set `SSL_CERT_FILE` for Python, `NODE_EXTRA_CA_CERTS` for Node). It still serves; say the data may not load. |

Use `localhost` links, never `127.0.0.1`: opti-ls CORS allows only the first. The server answers every path with the current file and never caches, so after a rebuild the user only reloads. Actions on these pages are real, so don't click them yourself. Only serving has a Node fallback: `build.py` and `brand.py` need Python 3.9+, so without Python say the skin can't be built on this machine. The built file also opens straight from disk with sample data, routed by `#<page>`; mention it as the offline option.

**Without a browser tool**, stop after giving the link, and say that rendering, overflow, broken images and clicking the actions were not checked. `build.py` has already checked the page contract. Ask them to send a screenshot or describe anything that looks wrong, then iterate.

**With a browser tool** (chrome-devtools), open the link and check each viewport, desktop `1280x800` and phone `390x844x3,mobile,touch` via `emulate`:

1. Navigate, read this skill's `scripts/verify.js`, and run `evaluate_script` with its full contents as `function`. Don't use `sourcePath`: chrome-devtools reads files only inside the project's folders, and this skill lives outside them. It opens every page and reports `rendered`, `overflowPx` with the elements that cause it, `brokenImages`, `navActive` and any JS errors. `ok: true` is required.
2. Screenshot the dashboard, missions and store at least, plus any page you changed.
3. In sample mode, click one action per page (claim, collect, buy, open, save name) and confirm the toast and the re-render. Never click actions in live mode unless the user says the player is a test account.

Reset emulation when you're done.

## 6. Iterate

"Make the cards rounder" means edit `styles.css`, rebuild, reload the link (re-run the checks if you have a browser tool). Edit only the files the change touches.

## Handing over

Give the user the `open` link from step 5 and the file path, where the brand came from (pasted code, URL, folder or brandbook), which data the build used (invented, seed sample, or live and for which player), what you checked and at which viewports, or that nothing was checked in a browser, and anything you couldn't check, such as states the sample player doesn't reach. A real brand's skin stays local: don't publish it to an artifact or share link without the user's say-so.
