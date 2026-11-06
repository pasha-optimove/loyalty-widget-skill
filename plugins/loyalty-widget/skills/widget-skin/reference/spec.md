# Widget skin spec

The page contract, hard rules, GamifySDK reference and every `state` shape. `scripts/build.py` enforces the contract and injects GamifySDK (`scripts/gamify-sdk.js`), which reads the player's data and runs their actions through the same player APIs the live widget uses.

## Parts

| file | content |
|---|---|
| `styles.css` | The shared brand style sheet. Only a Google Fonts `@import` is allowed. |
| `shell.html` | Header, navigation, and one element with `data-gamify-outlet`. |
| `<page>.html` | One fragment per page: `dashboard`, `levels`, `missions`, `tournaments`, `badges`, `store`, `lootboxes`, `profile`. Markup plus optional `<style>` and `<script>`. Never a full document. |

Build all pages. A page you leave out is reported as `MISSING`, and players would lose that feature.

## Page contract

`build.py` refuses a skin when any page breaks this contract and lists every problem, so fix all of them before you rebuild.

| page | must call | shows |
|---|---|---|
| `shell` | — (must contain `data-gamify-outlet`) | header, navigation, outlet |
| `dashboard` | — | overview: main level, balances, missions to claim, live tournaments, shortcuts |
| `levels` | `levels.claim` | every level system: current level, XP progress, next level, its rewards, claim button per claimable level |
| `missions` | `missions.claim`, `missions.unlock` | every mission, each in its state: locked (unlock cost) / not started / in progress / ready to claim / claimed |
| `tournaments` | `tournaments.enroll`, `tournaments.leaderboard` | upcoming / ongoing / finished, enrolled or not, rank, score, prize tiers, leaderboard |
| `badges` | — | owned and not-yet-owned badges, by rarity |
| `store` | `store.buyItem`, `store.buyBundle` | items and bundles by category, price, sale price, sold out, tag |
| `lootboxes` | `lootboxes.open` | boxes, key cost, possible prizes, the opening result |
| `profile` | `player.updateName` | name (editable), avatar, balances, badges |

Every page script registers itself:

```html
<section class="levels"></section>
<script>
GamifySDK.definePage('levels', function (root, sdk) {
  function render() {
    root.querySelector('.levels').innerHTML = sdk.state.levels.map(card).join('');
  }
  root.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-claim]');
    if (!btn) return;
    btn.disabled = true;
    sdk.levels.claim(btn.dataset.config, Number(btn.dataset.level))
      .catch(function () { btn.disabled = false; showError(root); });
  });
  sdk.on('change', render);
  render();
});
</script>
```

`definePage` runs each time the player opens the page. `sdk.on('change', ...)` listeners are removed automatically when they leave it. Return a function from the page if it needs extra cleanup (timers, for example).

Navigation: any element with `data-gamify-nav="<page>"` opens that page and gets `is-active` plus `aria-current="page"` while that page is open. You can also call `GamifySDK.navigate('<page>')`. Never build page URLs yourself, because the address depends on where the skin is served.

## Addresses

Served under the same paths as the live widget, the address names the player and the brand:

| address | player | brand |
|---|---|---|
| `/<tenantId>/brand/<brandName>/<playerId>/<page>` | `playerId` | the brand with that name |
| `/<tenantId>/<playerId>/<page>` | `playerId` | the tenant's default brand |

An address always shows real data from the tenant, brand and player it names, whatever data the file was built with: the skin finds the tenant in its region, looks the brand up by name, and reads everything through the live player APIs. Actions there are real too, so open only test players. An address without a page opens the first page. An unknown tenant or brand loads nothing and sets `state.errors.brand` (`404`), so show a "this link is not valid" message when it is set. Brands that require signed-in players need `?token=<player JWT>`. Opened as a plain file, the skin uses `#<page>` and the data it was built with.

## Hard rules

1. **Everything goes through GamifySDK.** The following are refused: `fetch`, `XMLHttpRequest`, `WebSocket`, `EventSource`, `sendBeacon`, `import()`, `<script src>`, `<link>`, `<iframe>`, `<object>`, `<embed>`, `<base>`, `<meta>`, and `document.cookie`.
2. **Any count, any data.** A player can have 0 or 40 missions, 1 or 6 level systems, empty store categories, a missing name or a missing icon. Derive every layout from the data. Never hardcode a number of cards, levels or tiers. Every list has an empty state written in the brand's voice.
3. **Icons can be missing.** Image fields are often empty. Pass them through `sdk.asset(path)` and fall back to an initial, an emoji or a CSS shape. Never leave a broken image or a blank gap.
4. **Every state is designed.** Locked, in progress, ready to claim, claimed, sold out, on sale, upcoming, ongoing, finished, enrolled, max level. The sample player is built to show most of them, so check each one.
5. **Actions are async.** Disable the control while the promise runs. On a rejection, re-enable it and show a short message. State refreshes on its own, and `change` fires.
6. **Responsive.** The widget runs from a phone up to desktop. `sdk.breakpoint` is `sm | md | lg | xl`, and `change` fires when it changes. Prefer CSS (container queries, `clamp`, grid `auto-fill`).
7. **Escape what you render.** Names come from players and marketers. Escape `& < > " '` before writing any value into HTML.
8. **Don't invent data.** Show only what `sdk.state` holds. No made-up prices, ranks or rewards.

## GamifySDK reference

### Core

| member | meaning |
|---|---|
| `GamifySDK.state` | everything the widget knows about the player (below) |
| `GamifySDK.on('change', fn)` | `fn(state)` after load, after every action, and on breakpoint change; returns `off()` |
| `GamifySDK.definePage(name, fn)` | `fn(root, sdk)` mounts the page into the outlet; may return a cleanup function |
| `GamifySDK.navigate(name)` / `.page` / `.pages` | routing (see Addresses) |
| `GamifySDK.route` | `{tenantId, brandName, customerId}` read from the address (`brandName` is `null` for the default brand), or `null` when opened as a file |
| `GamifySDK.reward(id)` | the reward definition `{id, name, type, icon, tag, description}`, or `null` |
| `GamifySDK.balance(rewardId)` | the player's amount of a currency, key or XP reward |
| `GamifySDK.asset(path)` | a full image URL for an icon or image path; `''` when empty |
| `GamifySDK.breakpoint` | `sm` < 640px ≤ `md` < 1024px ≤ `lg` < 1440px ≤ `xl` |
| `GamifySDK.mode` | `sample` or `live` |
| `GamifySDK.ready(fn)` | runs after the first data load |
| `GamifySDK.refresh()` | reload everything (live mode) |

### Actions (each returns a Promise)

| call | effect |
|---|---|
| `levels.claim(levelConfigId, levelNumber)` | claim a reached level's rewards |
| `missions.claim(objectiveId)` | claim a completed mission's rewards |
| `missions.unlock(objectiveId)` | pay the unlock cost of a locked mission |
| `tournaments.enroll(tournamentId)` | join a tournament |
| `tournaments.leaderboard(tournamentId, rankFrom=1, rankTo=10)` | resolves `[{playerId, playerName, rank, score}]` |
| `store.buyItem(itemId)` / `store.buyBundle(bundleId)` | buy; each purchase is sent once even if retried |
| `lootboxes.open(lootboxId)` | resolves `{draws:[{rewardId, rewardName, rewardIcon, amount}], keysSpent}`; animate the reveal from `draws` |
| `player.updateName(name)` | 1–50 characters |

A rejection carries `error.status`: `400` means not allowed (not enough balance, sold out, wrong state), `401` means signed out, and anything else is temporary. A claim that is already done resolves quietly.

### `state` shapes

These are the same shapes the live widget receives.

```text
player       {id, name, icon}
balances     [{rewardTypeId, totalAmount}]
rewards      [{id, name, type: currency|progression|badge|external|lootbox_key, icon, tag: common|rare|epic|legendary, description}]
badges       [reward]                       badges the player owns
levels       [LevelInfo]                    one per level system; isMain marks the primary one
mainLevel    LevelInfo | null
LevelInfo    {levelConfigId, configName, isMain, currentLevel, levelName, levelIcon,
              nextLevelName, nextLevelIcon, totalXp, xpForCurrentLevel, xpForNextLevel (null at max),
              xpProgressInCurrentLevel, maxLevel, isMaxLevel,
              currentLevelRewards [{rewardId, amount}], nextLevelRewards [{rewardId, amount}],
              claimableLevels [{levelNumber, name, levelIcon, rewards [{rewardId, amount}]}]}
missions     [{objective {id, name, description, icon, type: mission|task, goal, failAt,
                          unlockCurrencyId, unlockAmount, isRepeatable, repeatLimit},
               mission {status: active|completed|failed|locked|claimed, progress, repeatCount} | null,
               rewards [{rewardTypeId, amount}]}]
              mission null = not started; completed = ready to claim
tournaments  [{tournament {id, name, description, status, startDate, endDate, participationCount,
                           rewards [{rankFrom, rankTo, rewardId, amount}]},
               isEnrolled, enrolledAt, playerRank, playerScore, participantsCount,
               timeStatus: upcoming|ongoing|finished, playerReward}]
store        {items [{id, title, rewardId, rewardQuantity, priceCurrencyId, priceCurrencyName, priceCurrencyIcon,
                      basePrice, effectivePrice, onSale, soldOut, discountEndsAt, image,
                      categoryId, categoryName, tagName, tagColor}],
              bundles [{...same price fields, title, image, items [{title, rewardId, rewardQuantity, rewardIcon, rewardType}]}]}
lootboxes    [{id, name, description, image, drawCount,
               keys [{keyRewardId, keyName, keyIcon, amount}],
               prizes [{id, rewardId, rewardName, rewardIcon, amount, weight, exhausted}]}]
errors       {<state key>: status}          live mode: a part that failed to load; brand: 404 when the address names an unknown brand
```

XP progress inside a level is `xpProgressInCurrentLevel / (xpForNextLevel - xpForCurrentLevel)`.

## Data

| how it's opened | data |
|---|---|
| At a widget address, served by `scripts/serve.py` | Real data for the tenant, brand and player in the address (see Addresses). Actions are real. |
| As a file, built without a seed | An invented sample player and catalog. Actions change the sample state, so claiming, buying and opening all work. |
| As a file, built with `--seed` | The data in the seed: a brand's real catalog with a simulated player, or a live player. |
