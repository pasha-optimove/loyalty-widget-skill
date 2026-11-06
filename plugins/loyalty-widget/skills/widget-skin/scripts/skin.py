from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path


SDK_VERSION = "0.1.0"
SHELL = "shell"

_SDK_PATH = Path(__file__).resolve().parent / "gamify-sdk.js"


@dataclass(frozen=True)
class OptiLsHost:
    api_url: str
    cdn_url: str


_PROD_REGIONS = ("eu", "us")
_PRE_PROD_REGIONS = ("dev", "qa", "staging")


def _host(region: str) -> OptiLsHost:
    pre_prod = region in _PRE_PROD_REGIONS
    return OptiLsHost(
        api_url=f"https://opti-ls-api-{'qa' if pre_prod else region}.optimove.net/api",
        cdn_url=f"https://opti-ls-images-{'dev' if pre_prod else region}.optimove.net",
    )


def opti_ls_hosts(first_region: str = "eu") -> tuple[OptiLsHost, ...]:
    first = first_region.lower()
    if first in _PRE_PROD_REGIONS:
        return (_host(first),)
    return tuple(_host(r) for r in dict.fromkeys((first, *_PROD_REGIONS)))


@dataclass(frozen=True)
class PageContract:
    key: str
    label: str
    required_calls: tuple[str, ...]


PAGE_CONTRACTS: tuple[PageContract, ...] = (
    PageContract("dashboard", "Dashboard", ()),
    PageContract("levels", "Levels", ("levels.claim",)),
    PageContract("missions", "Missions", ("missions.claim", "missions.unlock")),
    PageContract("tournaments", "Tournaments", ("tournaments.enroll", "tournaments.leaderboard")),
    PageContract("badges", "Badges", ()),
    PageContract("store", "Store", ("store.buyItem", "store.buyBundle")),
    PageContract("lootboxes", "Lootboxes", ("lootboxes.open",)),
    PageContract("profile", "Profile", ("player.updateName",)),
)
PAGE_KEYS: tuple[str, ...] = tuple(c.key for c in PAGE_CONTRACTS)
_CONTRACT_BY_KEY = {c.key: c for c in PAGE_CONTRACTS}

_STYLE_RE = re.compile(r"<style\b[^>]*>(.*?)</style\s*>", re.IGNORECASE | re.DOTALL)
_SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.IGNORECASE | re.DOTALL)
_FULL_DOCUMENT_RE = re.compile(r"<!doctype|<html\b|<head\b|<body\b", re.IGNORECASE)
_OUTLET_RE = re.compile(r"\bdata-gamify-outlet\b")
_NAV_RE = re.compile(r"""data-gamify-nav\s*=\s*["']([\w-]+)["']""")
_IMPORT_RE = re.compile(r"""@import\s+(?:url\()?\s*["']?([^"')\s;]+)""", re.IGNORECASE)
_ALLOWED_IMPORT_HOSTS = ("https://fonts.googleapis.com/",)

_FORBIDDEN: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("an external <script src>", re.compile(r"<script\b[^>]*\bsrc\s*=", re.IGNORECASE)),
    ("a <link> tag", re.compile(r"<link\b", re.IGNORECASE)),
    ("an <iframe>, <object> or <embed>", re.compile(r"<(iframe|object|embed)\b", re.IGNORECASE)),
    ("a <base> or <meta> tag", re.compile(r"<(base|meta)\b", re.IGNORECASE)),
    ("a direct network call (fetch, XMLHttpRequest, WebSocket, EventSource, sendBeacon)",
     re.compile(r"\bfetch\s*\(|XMLHttpRequest|\bWebSocket\b|\bEventSource\b|sendBeacon", re.IGNORECASE)),
    ("a dynamic import()", re.compile(r"\bimport\s*\(")),
    ("document.cookie", re.compile(r"document\s*\.\s*cookie")),
)


@dataclass(frozen=True)
class SkinIssue:
    page: str
    detail: str


@dataclass(frozen=True)
class PageFragment:
    key: str
    markup: str
    styles: str
    scripts: str

    @classmethod
    def parse(cls, key: str, source: str) -> "PageFragment":
        styles = "\n".join(m.group(1).strip() for m in _STYLE_RE.finditer(source))
        scripts = "\n".join(m.group(2).strip() for m in _SCRIPT_RE.finditer(source))
        markup = _SCRIPT_RE.sub("", _STYLE_RE.sub("", source)).strip()
        return cls(key=key, markup=markup, styles=styles, scripts=scripts)

    @property
    def nav_targets(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(_NAV_RE.findall(self.markup)))


@dataclass(frozen=True)
class SkinSource:
    styles: str
    shell: PageFragment
    pages: tuple[PageFragment, ...]

    @property
    def page_keys(self) -> tuple[str, ...]:
        return tuple(p.key for p in self.pages)

    @property
    def missing_pages(self) -> tuple[str, ...]:
        built = set(self.page_keys)
        return tuple(k for k in PAGE_KEYS if k not in built)

    @property
    def dangling_nav(self) -> tuple[str, ...]:
        built = set(self.page_keys)
        targets = list(self.shell.nav_targets)
        for p in self.pages:
            targets.extend(p.nav_targets)
        return tuple(t for t in dict.fromkeys(targets) if t not in built)


def _forbidden_in(text: str) -> list[str]:
    return [label for label, pattern in _FORBIDDEN if pattern.search(text)]


def _bad_imports(css: str) -> list[str]:
    return [url for url in _IMPORT_RE.findall(css) if not url.startswith(_ALLOWED_IMPORT_HOSTS)]


def _calls(scripts: str, call: str) -> bool:
    area, method = call.split(".")
    return re.search(rf"\b{area}\s*\.\s*{method}\s*\(", scripts) is not None


def _defines(scripts: str, key: str) -> bool:
    return re.search(rf"""definePage\s*\(\s*["']{key}["']""", scripts) is not None


def _check_fragment(fragment: PageFragment, raw: str) -> list[SkinIssue]:
    issues: list[SkinIssue] = []
    if _FULL_DOCUMENT_RE.search(raw):
        issues.append(SkinIssue(fragment.key, "is a full HTML document; send only the page fragment"))
    for label in _forbidden_in(raw):
        issues.append(SkinIssue(fragment.key, f"contains {label}; every read and action goes through GamifySDK"))
    for url in _bad_imports(fragment.styles):
        issues.append(SkinIssue(fragment.key, f"imports '{url}'; only Google Fonts may be imported"))
    if fragment.key == SHELL:
        if not _OUTLET_RE.search(fragment.markup):
            issues.append(SkinIssue(SHELL, "has no element with data-gamify-outlet, so no page can render"))
        return issues
    if not fragment.markup and not fragment.scripts:
        issues.append(SkinIssue(fragment.key, "is empty"))
        return issues
    if not _defines(fragment.scripts, fragment.key):
        issues.append(SkinIssue(fragment.key, f"never calls GamifySDK.definePage('{fragment.key}', ...)"))
    for call in _CONTRACT_BY_KEY[fragment.key].required_calls:
        if not _calls(fragment.scripts, call):
            issues.append(SkinIssue(fragment.key, f"never calls {call}(), so players lose that feature"))
    return issues


def parse_skin(pages: dict[str, str], styles: str) -> tuple[SkinSource | None, list[SkinIssue]]:
    issues: list[SkinIssue] = []
    for key in pages:
        if key != SHELL and key not in _CONTRACT_BY_KEY:
            issues.append(SkinIssue(key, "is not a widget page"))
    if SHELL not in pages:
        issues.append(SkinIssue(SHELL, "is missing; the shell holds the header, the navigation and the page outlet"))
    for label in _forbidden_in(styles):
        issues.append(SkinIssue("styles", f"contains {label}"))
    for url in _bad_imports(styles):
        issues.append(SkinIssue("styles", f"imports '{url}'; only Google Fonts may be imported"))

    fragments: dict[str, PageFragment] = {}
    for key, raw in pages.items():
        if key != SHELL and key not in _CONTRACT_BY_KEY:
            continue
        fragment = PageFragment.parse(key, raw or "")
        fragments[key] = fragment
        issues.extend(_check_fragment(fragment, raw or ""))

    if issues:
        return None, issues
    ordered = tuple(fragments[k] for k in PAGE_KEYS if k in fragments)
    if not ordered:
        return None, [SkinIssue("pages", "has no widget page besides the shell")]
    return SkinSource(styles=styles, shell=fragments[SHELL], pages=ordered), []


def _script_safe(text: str) -> str:
    return re.sub(r"</(script)", r"<\\/\1", text, flags=re.IGNORECASE)


def _json_for_script(value: object) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def sdk_source() -> str:
    return _SDK_PATH.read_text()


@dataclass(frozen=True)
class LiveTarget:
    api_url: str
    brand_id: str
    customer_id: str


@dataclass(frozen=True)
class SkinRuntime:
    mode: str
    title: str
    cdn_url: str
    sample: dict | None = None
    sample_leaderboards: dict | None = None
    live: LiveTarget | None = None
    hosts: tuple[OptiLsHost, ...] = ()

    def as_config(self, source: SkinSource) -> dict:
        cfg: dict = {
            "sdkVersion": SDK_VERSION,
            "mode": self.mode,
            "pages": list(source.page_keys),
            "defaultPage": source.page_keys[0],
            "cdnUrl": self.cdn_url,
        }
        if self.sample is not None:
            cfg["sample"] = self.sample
            cfg["sampleLeaderboards"] = self.sample_leaderboards or {}
        if self.hosts:
            cfg["hosts"] = [{"apiUrl": h.api_url, "cdnUrl": h.cdn_url} for h in self.hosts]
        if self.live is not None:
            cfg["live"] = {
                "apiUrl": self.live.api_url,
                "brandId": self.live.brand_id,
                "customerId": self.live.customer_id,
            }
        return cfg


def assemble(source: SkinSource, runtime: SkinRuntime) -> str:
    page_styles = "\n".join(f.styles for f in (source.shell, *source.pages) if f.styles)
    templates = "\n".join(
        f'<template data-gamify-page="{p.key}">\n{p.markup}\n</template>' for p in source.pages
    )
    scripts = "\n".join(
        f"<script>\n{_script_safe(f.scripts)}\n</script>" for f in (source.shell, *source.pages) if f.scripts
    )
    title = re.sub(r"[<>&]", "", runtime.title)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title}</title>\n"
        f"<style>\n{source.styles}\n</style>\n"
        f"<style>\n{page_styles}\n</style>\n"
        "</head>\n<body>\n"
        f"{source.shell.markup}\n"
        f"{templates}\n"
        f"<script>window.__GAMIFY__ = {_json_for_script(runtime.as_config(source))};</script>\n"
        f"<script>\n{_script_safe(sdk_source())}\n</script>\n"
        f"{scripts}\n"
        "</body>\n</html>\n"
    )


@dataclass
class SampleData:
    state: dict
    leaderboards: dict
    sources: dict[str, str] = field(default_factory=dict)


_SAMPLE_NAMES = ("Maya", "Leo", "Noa", "Kai", "Ivy", "Theo", "Zoe", "Max", "Lia", "Sam", "Ava", "Eli")


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _by_type(rewards: list[dict], kind: str) -> list[dict]:
    return [r for r in rewards if r.get("type") == kind]


def _invented_rewards(brand_id: str) -> list[dict]:
    rows = [
        ("sample-coins", "Coins", "currency", None),
        ("sample-xp", "XP", "progression", None),
        ("sample-key", "Golden key", "lootbox_key", None),
        ("sample-badge-1", "First steps", "badge", "common"),
        ("sample-badge-2", "High roller", "badge", "rare"),
        ("sample-badge-3", "Legend", "badge", "legendary"),
        ("sample-spins", "10 free spins", "external", None),
    ]
    return [
        {"id": rid, "name": name, "type": kind, "tag": tag, "icon": None, "brandId": brand_id, "description": None}
        for rid, name, kind, tag in rows
    ]


def _usable_level_configs(configs: list[dict]) -> list[dict]:
    active = [c for c in configs if c.get("status") == "active" and c.get("levels")]
    return active or [c for c in configs if c.get("status") != "archived" and c.get("levels")]


def _invented_ladder(xp_id: str, coin_id: str, now: datetime) -> dict:
    names = ("Rookie", "Bronze", "Silver", "Gold", "Platinum", "Diamond")
    return {
        "id": "sample-ladder",
        "name": "VIP ladder",
        "isMain": True,
        "status": "active",
        "xpRewardId": xp_id,
        "levels": [
            {
                "id": f"sample-level-{i + 1}",
                "levelNumber": i + 1,
                "name": n,
                "requiredXp": i * i * 500,
                "iconUrl": None,
                "rewards": [{"id": f"sample-lr-{i + 1}", "levelId": f"sample-level-{i + 1}",
                             "rewardId": coin_id, "amount": (i + 1) * 100, "createdAt": _iso(now)}] if i else [],
            }
            for i, n in enumerate(names)
        ],
    }


def _level_rewards(level: dict, now: datetime) -> list[dict]:
    return [
        {
            "id": r.get("id") or f"{level.get('id')}-r{i}",
            "levelId": level.get("id"),
            "rewardId": r.get("rewardId"),
            "amount": r.get("amount") or 1,
            "createdAt": r.get("createdAt") or _iso(now),
        }
        for i, r in enumerate(level.get("rewards") or [])
    ]


def _player_level(config: dict, now: datetime) -> dict:
    ladder = sorted(config.get("levels") or [], key=lambda lv: lv.get("levelNumber") or 0)
    idx = max(0, (len(ladder) - 1) // 2)
    cur = ladder[idx]
    nxt = ladder[idx + 1] if idx + 1 < len(ladder) else None
    floor_xp = cur.get("requiredXp") or 0
    next_xp = nxt.get("requiredXp") if nxt else None
    total = floor_xp + (int((next_xp - floor_xp) * 0.6) if next_xp is not None else 0)
    claimable = [
        {
            "levelNumber": lv.get("levelNumber"),
            "name": lv.get("name"),
            "levelIcon": lv.get("iconUrl"),
            "rewards": _level_rewards(lv, now),
        }
        for lv in ladder[: idx + 1]
        if lv.get("rewards")
    ][-1:]
    return {
        "levelConfigId": config.get("id"),
        "configName": config.get("name"),
        "isMain": bool(config.get("isMain")),
        "currentLevel": cur.get("levelNumber"),
        "levelName": cur.get("name"),
        "levelIcon": cur.get("iconUrl"),
        "nextLevelName": nxt.get("name") if nxt else None,
        "nextLevelIcon": nxt.get("iconUrl") if nxt else None,
        "totalXp": total,
        "xpForCurrentLevel": floor_xp,
        "xpForNextLevel": next_xp,
        "xpProgressInCurrentLevel": total - floor_xp,
        "maxLevel": ladder[-1].get("levelNumber"),
        "isMaxLevel": nxt is None,
        "currentLevelRewards": _level_rewards(cur, now),
        "nextLevelRewards": _level_rewards(nxt, now) if nxt else [],
        "claimableLevels": claimable,
    }


def _objective_rewards(objective: dict) -> list[dict]:
    out: list[dict] = []
    for rule in objective.get("ruleConfigs") or []:
        rule = rule or {}
        params = ((rule.get("event") or {}).get("params")) or {}
        for r in (rule.get("rewards") or []) + (params.get("rewards") or []):
            rid = r.get("rewardTypeId") or r.get("rewardId")
            if rid:
                out.append({"rewardTypeId": rid, "amount": r.get("amount") or 1})
    return out


def _usable_objectives(objectives: list[dict]) -> list[dict]:
    loyal = [o for o in objectives if o.get("type") in ("mission", "task")]
    active = [o for o in loyal if o.get("status") == "active"]
    return (active or [o for o in loyal if o.get("status") not in ("archived", "deleted")])[:12]


def _invented_objectives(coin_id: str) -> list[dict]:
    rows = (
        ("Place 5 bets", "Place any 5 bets this week", 5, None),
        ("Deposit 100", "Make deposits worth 100 in total", 100, None),
        ("Daily login", "Open the app today", 1, None),
        ("High-stakes run", "Win 3 bets above 50", 3, 250),
        ("Weekend warrior", "Play on Saturday and Sunday", 2, None),
    )
    return [
        {
            "id": f"sample-mission-{i}",
            "name": name,
            "description": desc,
            "type": "mission" if goal > 1 else "task",
            "goal": goal,
            "unlockCurrencyId": coin_id if unlock else None,
            "unlockAmount": unlock,
            "isRepeatable": i == 2,
            "status": "active",
            "ruleConfigs": [{"rewards": [{"rewardTypeId": coin_id, "amount": 50 * (i + 1)}]}],
        }
        for i, (name, desc, goal, unlock) in enumerate(rows)
    ]


def _mission_row(objective: dict, index: int, fallback_reward: str | None, now: datetime) -> dict:
    goal = objective.get("goal") or 1
    if objective.get("unlockAmount"):
        status, progress = "locked", 0
    else:
        status, progress = (
            ("active", max(1, int(goal * 0.6)) if goal > 1 else 0),
            ("completed", goal),
            ("claimed", goal),
            ("active", 0),
        )[index % 4]
    rewards = _objective_rewards(objective)
    if not rewards and fallback_reward:
        rewards = [{"rewardTypeId": fallback_reward, "amount": 100}]
    return {
        "objective": {
            "id": objective.get("id"),
            "name": objective.get("name"),
            "description": objective.get("description"),
            "icon": objective.get("icon"),
            "type": objective.get("type"),
            "goal": goal,
            "failAt": objective.get("failAt") or _iso(now + timedelta(days=3 + index)),
            "unlockCurrencyId": objective.get("unlockCurrencyId"),
            "unlockAmount": objective.get("unlockAmount"),
            "optInRequired": bool(objective.get("optInRequired")),
            "isRepeatable": bool(objective.get("isRepeatable")),
            "repeatLimit": objective.get("repeatLimit"),
            "status": "active",
        },
        "mission": {
            "status": status,
            "progress": progress,
            "repeatCount": 0,
            "objectiveId": objective.get("id"),
            "playerId": "sample-player",
            "createdAt": _iso(now - timedelta(days=2)),
            "updatedAt": _iso(now),
        },
        "rewards": rewards,
    }


def _store(rewards: list[dict], currency: dict | None, now: datetime) -> dict:
    if currency is None:
        return {"items": [], "bundles": []}
    goods = [r for r in rewards if r.get("type") in ("external", "badge", "lootbox_key") and r is not currency][:6]
    items = []
    for i, r in enumerate(goods):
        base = 250 * (i + 1)
        on_sale = i == 1
        items.append({
            "id": f"sample-item-{i}",
            "title": r.get("name"),
            "rewardId": r.get("id"),
            "rewardQuantity": 1,
            "priceCurrencyId": currency.get("id"),
            "priceAmount": base,
            "priceCurrencyName": currency.get("name"),
            "priceCurrencyIcon": currency.get("icon"),
            "categoryId": "sample-category-" + ("featured" if i < 3 else "more"),
            "categoryName": "Featured" if i < 3 else "More rewards",
            "tagId": "sample-tag-hot" if i == 0 else None,
            "tagName": "Hot" if i == 0 else None,
            "tagColor": "#E5484D" if i == 0 else None,
            "basePrice": base,
            "effectivePrice": int(base * 0.8) if on_sale else base,
            "onSale": on_sale,
            "soldOut": i == len(goods) - 1 and len(goods) > 2,
            "discountEndsAt": _iso(now + timedelta(days=2)) if on_sale else None,
            "image": r.get("icon"),
        })
    bundles = []
    if len(goods) >= 2:
        members = [
            {"id": it["id"], "title": it["title"], "rewardId": it["rewardId"], "rewardQuantity": 1,
             "rewardIcon": it["image"], "rewardType": next((g.get("type") for g in goods if g.get("id") == it["rewardId"]), None)}
            for it in items[:2]
        ]
        base = sum(it["basePrice"] for it in items[:2])
        bundles.append({
            "id": "sample-bundle-0",
            "title": "Starter pack",
            "priceCurrencyId": currency.get("id"),
            "priceAmount": base,
            "priceCurrencyName": currency.get("name"),
            "priceCurrencyIcon": currency.get("icon"),
            "categoryId": "sample-category-featured",
            "categoryName": "Featured",
            "tagId": None, "tagName": None, "tagColor": None,
            "basePrice": base,
            "effectivePrice": int(base * 0.7),
            "onSale": True,
            "soldOut": False,
            "discountEndsAt": _iso(now + timedelta(days=5)),
            "image": None,
            "items": members,
        })
    return {"items": items, "bundles": bundles}


def _lootboxes(rewards: list[dict], key: dict | None) -> list[dict]:
    if key is None:
        return []
    prizes = [r for r in rewards if r.get("type") in ("currency", "external", "badge")][:5]
    if not prizes:
        return []
    return [{
        "id": "sample-lootbox-0",
        "name": "Mystery chest",
        "description": "Open it for a random prize",
        "image": None,
        "keys": [{"keyRewardId": key.get("id"), "keyName": key.get("name"), "keyIcon": key.get("icon"), "amount": 1}],
        "drawCount": 1,
        "prizes": [
            {"id": f"sample-prize-{i}", "rewardId": p.get("id"), "rewardName": p.get("name"),
             "rewardIcon": p.get("icon"), "amount": 50 * (i + 1) if p.get("type") == "currency" else 1,
             "weight": 5 - i, "exhausted": False}
            for i, p in enumerate(prizes)
        ],
    }]


def _tournaments(rewards: list[dict], now: datetime) -> tuple[list[dict], dict]:
    payout = next(iter(_by_type(rewards, "currency") + _by_type(rewards, "external")), None)
    specs = (
        ("sample-tournament-0", "Weekend sprint", now - timedelta(days=1), now + timedelta(days=2), True, 4, "active"),
        ("sample-tournament-1", "Monthly masters", now + timedelta(days=3), now + timedelta(days=30), False, None, "active"),
        ("sample-tournament-2", "Spring cup", now - timedelta(days=20), now - timedelta(days=5), True, 12, "archived"),
    )
    rows: list[dict] = []
    boards: dict[str, list[dict]] = {}
    for tid, name, start, end, enrolled, rank, status in specs:
        tiers = [
            {"rankFrom": 1, "rankTo": 1, "rewardId": payout.get("id"), "amount": 1000},
            {"rankFrom": 2, "rankTo": 5, "rewardId": payout.get("id"), "amount": 250},
            {"rankFrom": 6, "rankTo": 20, "rewardId": payout.get("id"), "amount": 50},
        ] if payout else []
        tournament = {
            "id": tid, "name": name, "description": f"{name}: climb the leaderboard to win.",
            "status": status, "startDate": _iso(start), "endDate": _iso(end),
            "participationCount": 0 if rank is None else 240, "rewards": tiers,
        }
        score = None if rank is None else 5000 - rank * 180
        reward = next((t for t in tiers if rank is not None and t["rankFrom"] <= rank <= t["rankTo"]), None)
        status_label = "upcoming" if start > now else ("finished" if end < now or status == "archived" else "ongoing")
        rows.append({
            "tournament": tournament, "isEnrolled": enrolled, "enrolledAt": _iso(start) if enrolled else None,
            "playerRank": rank, "playerScore": score, "participantsCount": tournament["participationCount"],
            "timeStatus": status_label, "playerReward": reward,
        })
        if rank is not None:
            boards[tid] = [
                {"playerId": "sample-player" if r == rank else f"p-{r}",
                 "playerName": "You" if r == rank else _SAMPLE_NAMES[(r - 1) % len(_SAMPLE_NAMES)] + f" {r}",
                 "rank": r, "score": 5000 - r * 180}
                for r in range(1, 26)
            ]
    return rows, boards


@dataclass(frozen=True)
class BrandCatalog:
    store_items: list[dict] | None = None
    store_bundles: list[dict] | None = None
    leaderboards: list[dict] | None = None


def _time_status(board: dict, now: datetime) -> str:
    if board.get("status") in ("rewarding", "archived"):
        return "finished"
    try:
        start = datetime.fromisoformat(str(board.get("startDate")).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(board.get("endDate")).replace("Z", "+00:00"))
    except ValueError:
        return "ongoing"
    if now < start:
        return "upcoming"
    return "finished" if now > end else "ongoing"


def _real_tournaments(boards: list[dict], now: datetime) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    standings: dict[str, list[dict]] = {}
    for i, board in enumerate(boards):
        status = _time_status(board, now)
        enrolled = status != "upcoming" and i % 3 != 2
        rank = (3 + i * 4) if enrolled else None
        score = None if rank is None else max(0, 5000 - rank * 180)
        tiers = board.get("rewards") or []
        reward = next((t for t in tiers if rank is not None and (t.get("rankFrom") or 0) <= rank <= (t.get("rankTo") or 0)), None)
        rows.append({
            "tournament": board, "isEnrolled": enrolled, "enrolledAt": board.get("startDate") if enrolled else None,
            "playerRank": rank, "playerScore": score,
            "participantsCount": board.get("participationCount"), "timeStatus": status, "playerReward": reward,
        })
        if rank is not None and board.get("id"):
            standings[board["id"]] = [
                {"playerId": "sample-player" if r == rank else f"p-{r}",
                 "playerName": "You" if r == rank else _SAMPLE_NAMES[(r - 1) % len(_SAMPLE_NAMES)] + f" {r}",
                 "rank": r, "score": max(0, 5000 - r * 180)}
                for r in range(1, max(rank, 10) + 1)
            ]
    return rows, standings


def build_sample_state(
    rewards: list[dict],
    level_configs: list[dict],
    objectives: list[dict],
    brand_id: str,
    now: datetime,
    brand_catalog: BrandCatalog = BrandCatalog(),
) -> SampleData:
    sources: dict[str, str] = {}
    tenant_rewards = [r for r in rewards if r.get("id")]
    if tenant_rewards:
        sources["rewards"] = "tenant"
        catalog = tenant_rewards
    else:
        sources["rewards"] = "invented"
        catalog = _invented_rewards(brand_id)

    currency = next(iter(_by_type(catalog, "currency")), None)
    xp = next(iter(_by_type(catalog, "progression")), None)
    key = next(iter(_by_type(catalog, "lootbox_key")), None)

    configs = _usable_level_configs(level_configs)
    if configs:
        sources["levels"] = "tenant"
    else:
        sources["levels"] = "invented"
        configs = [_invented_ladder((xp or {}).get("id") or "sample-xp", (currency or {}).get("id") or "sample-coins", now)]
    levels = [_player_level(c, now) for c in configs]
    main = next((lv for lv in levels if lv["isMain"]), levels[0])

    picked = _usable_objectives(objectives)
    if picked:
        sources["missions"] = "tenant"
    else:
        sources["missions"] = "invented"
        picked = _invented_objectives((currency or {}).get("id") or "sample-coins")
    fallback = (currency or {}).get("id")
    missions = [_mission_row(o, i, fallback, now) for i, o in enumerate(picked)]

    badges = _by_type(catalog, "badge")
    owned = [{k: v for k, v in b.items() if k not in ("createdAt", "updatedAt")} for b in badges[: max(1, len(badges) // 2)]] if badges else []

    balances = []
    for r in catalog:
        kind = r.get("type")
        if kind == "currency":
            balances.append({"rewardTypeId": r["id"], "totalAmount": 1250})
        elif kind == "lootbox_key":
            balances.append({"rewardTypeId": r["id"], "totalAmount": 3})
        elif kind == "progression":
            balances.append({"rewardTypeId": r["id"], "totalAmount": main["totalXp"]})

    if brand_catalog.leaderboards is not None:
        tournaments, boards = _real_tournaments(brand_catalog.leaderboards, now)
        sources["tournaments"] = "tenant"
    else:
        tournaments, boards = _tournaments(catalog, now)
        sources["tournaments"] = "invented from the brand's rewards"
    if brand_catalog.store_items is not None and brand_catalog.store_bundles is not None:
        store = {"items": brand_catalog.store_items, "bundles": brand_catalog.store_bundles}
        sources["store"] = "tenant"
    else:
        store = _store(catalog, currency, now)
        sources["store"] = "invented from the brand's rewards"
    sources["lootboxes"] = "invented from the brand's rewards"

    state = {
        "player": {"id": "sample-player", "name": "Alex Morgan", "icon": ""},
        "balances": balances,
        "rewards": catalog,
        "levels": levels,
        "mainLevel": main,
        "missions": missions,
        "badges": owned,
        "store": store,
        "lootboxes": _lootboxes(catalog, key),
        "tournaments": tournaments,
    }
    return SampleData(state=state, leaderboards=boards, sources=sources)
