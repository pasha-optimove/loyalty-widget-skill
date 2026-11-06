#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from skin import (  # noqa: E402
    PAGE_KEYS,
    SHELL,
    LiveTarget,
    OptiLsHost,
    SkinRuntime,
    assemble,
    build_sample_state,
    opti_ls_hosts,
    parse_skin,
)

_SEED_RE = re.compile(r"<script>window\.__GAMIFY__ = (.*?);</script>", re.DOTALL)


def read_project(project: Path) -> tuple[dict[str, str], str]:
    styles_path = project / "styles.css"
    styles = styles_path.read_text() if styles_path.exists() else ""
    pages = {}
    for key in (SHELL, *PAGE_KEYS):
        path = project / f"{key}.html"
        if path.exists():
            pages[key] = path.read_text()
    return pages, styles


def runtime_from_seed(seed: Path, title: str, region: str) -> SkinRuntime:
    match = _SEED_RE.search(seed.read_text())
    if not match:
        sys.exit(f"{seed} has no window.__GAMIFY__ config; build it with builder(action='create_widget_skin') first, or build without --seed")
    cfg = json.loads(match.group(1))
    live = cfg.get("live")
    return SkinRuntime(
        mode=cfg["mode"],
        title=title,
        cdn_url=cfg.get("cdnUrl", ""),
        sample=cfg.get("sample"),
        sample_leaderboards=cfg.get("sampleLeaderboards"),
        live=LiveTarget(api_url=live["apiUrl"], brand_id=live["brandId"], customer_id=live["customerId"]) if live else None,
        hosts=tuple(OptiLsHost(h["apiUrl"], h["cdnUrl"]) for h in cfg["hosts"]) if cfg.get("hosts") else opti_ls_hosts(region),
    )


def invented_runtime(title: str, region: str) -> SkinRuntime:
    sample = build_sample_state([], [], [], "sample-brand", datetime.now(timezone.utc))
    return SkinRuntime(
        mode="sample",
        title=title,
        cdn_url="",
        sample=sample.state,
        sample_leaderboards=sample.leaderboards,
        hosts=opti_ls_hosts(region),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Assemble a gamify widget skin from local page fragments.")
    parser.add_argument("project", type=Path)
    parser.add_argument("--seed", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--title")
    parser.add_argument("--region", default="eu")
    args = parser.parse_args()

    project = args.project.resolve()
    pages, styles = read_project(project)
    source, issues = parse_skin(pages, styles)
    if source is None:
        print("CONTRACT FAILED")
        for issue in issues:
            print(f"  {issue.page}: {issue.detail}")
        sys.exit(1)

    title = args.title or f"{project.name} widget skin"
    runtime = runtime_from_seed(args.seed, title, args.region) if args.seed else invented_runtime(title, args.region)
    out = (args.out or project / f"{project.name}.html").resolve()
    out.write_text(assemble(source, runtime))

    print(f"built     {out}")
    print(f"mode      {runtime.mode} ({'seed ' + str(args.seed) if args.seed else 'invented sample data'})")
    print(f"pages     {', '.join(source.page_keys)}")
    if source.missing_pages:
        print(f"MISSING   {', '.join(source.missing_pages)}")
    if source.dangling_nav:
        print(f"DANGLING  nav points at {', '.join(source.dangling_nav)}")
    print(f"size      {round(out.stat().st_size / 1024, 1)} KB")


if __name__ == "__main__":
    main()
