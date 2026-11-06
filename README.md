# Loyalty widget skill

A Claude Code marketplace with one plugin, `loyalty-widget`. It adds the `widget-skin` skill: design a fully custom gamify (opti-ls) loyalty widget from a brand's website or brandbook, then preview it on the same addresses as the live widget with real tenant data.

## Install

```
/plugin marketplace add pasha-optimove/loyalty-widget-skill
/plugin install loyalty-widget@loyalty-widget-skill
```

Then ask for it, for example "build a loyalty widget for https://example.com", paste the brand's CSS and say "build the widget from this", or run `/widget-skin`.

## What it does

1. Reads the brand's colors, type and voice with no browser: from code pasted into the chat (page source, CSS, Tailwind config, token JSON), a website's HTML and stylesheets over HTTP, a local site repo or token folder, or a brandbook (`scripts/brand.py`).
2. Writes the widget as small page files: shell, dashboard, levels, missions, tournaments, badges, store, lootboxes, profile.
3. Checks them against the page contract and assembles one self-contained HTML file with GamifySDK.
4. Asks for a tenant id and starts the preview itself (Python, or Node 18+ when Python is missing): it checks the tenant exists, picks a random player, and gives you a `http://localhost:8766/<tenantId>/<player>/dashboard` link that shows that tenant's real catalog.
5. When a browser tool is available, checks every page on desktop and phone: rendering, overflow, broken images, JS errors. Without one, it hands you the address to open yourself.

## Requirements

- Python 3.9 or newer for building. No packages to install: the page contract, the assembler and GamifySDK ship with the skill. Serving also runs on Node 18+.
- Optional: the chrome-devtools MCP server, for checking the result in a browser. Everything else works without a browser.
- Optional: the Optimove MCP, only to bake a brand's catalog into a file that opens without a server.

## Safety

At a widget address, actions (claim, buy, open, rename) are real and write to that player's account. Use test players only.
