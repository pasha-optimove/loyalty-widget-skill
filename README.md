# Loyalty widget skill

A Claude Code marketplace with one plugin, `loyalty-widget`. It adds the `widget-skin` skill: design a fully custom gamify (opti-ls) loyalty widget from a brand's website or brandbook, then preview it on the same addresses as the live widget with real tenant data.

## Install

```
/plugin marketplace add pasha-optimove/loyalty-widget-skill
/plugin install loyalty-widget@loyalty-widget-skill
```

Then ask for it, for example "build a loyalty widget for https://example.com", or run `/widget-skin`.

## What it does

1. Reads the brand's colors, type and voice from source, with no browser: a website's HTML and stylesheets over HTTP, or a local site repo, theme or token folder (`scripts/brand.py`). A brandbook works too. The browser is only a fallback for sites that build their look with JavaScript.
2. Writes the widget as small page files: shell, dashboard, levels, missions, tournaments, badges, store, lootboxes, profile.
3. Checks them against the page contract and assembles one self-contained HTML file with GamifySDK.
4. Serves it at `http://localhost:8766/<tenantId>/brand/<brandName>/<playerId>/<page>` (or `/<tenantId>/<playerId>/<page>` for the default brand). At that address the skin reads real data for that tenant, brand and player.
5. Checks every page in the browser on desktop and phone: rendering, overflow, broken images, JS errors.

## Requirements

- Python 3.9 or newer. No packages to install: the page contract, the assembler and GamifySDK ship with the skill.
- The chrome-devtools MCP server, for checking the result in a browser (and reading JavaScript-only sites).
- Optional: the Optimove MCP, only to bake a brand's catalog into a file that opens without a server.

## Safety

At a widget address, actions (claim, buy, open, rename) are real and write to that player's account. Use test players only.
