#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
import http.server
import json
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from skin import PAGE_KEYS, opti_ls_hosts  # noqa: E402


def handler_for(skin: Path) -> type[http.server.BaseHTTPRequestHandler]:
    class SkinHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = skin.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: object) -> None:
            pass

    return SkinHandler


def find_tenant(tenant: str, region: str) -> str | None:
    path = f"/brands/default/{urllib.parse.quote(tenant)}"
    unreachable = []
    for host in opti_ls_hosts(region):
        try:
            with urllib.request.urlopen(urllib.request.Request(host.api_url + path, headers={"Accept": "application/json"}), timeout=15) as res:
                found = json.loads(res.read() or b"{}")
            if found.get("id"):
                return host.api_url.split("//")[1].split(".")[0].rsplit("-", 1)[-1]
        except urllib.error.HTTPError as e:
            if e.code != 404:
                unreachable.append(f"{host.api_url} answered {e.code}")
        except (urllib.error.URLError, OSError, ValueError) as e:
            unreachable.append(f"{host.api_url} unreachable ({e.__class__.__name__})")
    if unreachable:
        print("warning: could not confirm the tenant: " + "; ".join(unreachable), file=sys.stderr)
        return "unknown"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve a widget skin on every path, the way the widget host does.")
    parser.add_argument("skin", type=Path)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--tenant", help="tenant id to preview with real data; checked before serving")
    parser.add_argument("--region", default="eu", help="region tried first when looking up the tenant")
    args = parser.parse_args()
    skin = args.skin.resolve()
    if not skin.is_file():
        sys.exit(f"{skin} does not exist; build it first")

    base = f"http://localhost:{args.port}"
    if args.tenant:
        if not args.tenant.isdigit():
            sys.exit(f"tenant id must be a number, got {args.tenant!r}")
        region = find_tenant(args.tenant, args.region)
        if region is None:
            sys.exit(f"tenant {args.tenant} was not found in any region; check the tenant id")
        player = f"player-{secrets.token_hex(3)}"
        prefix = f"/{args.tenant}/{player}"
        print(f"tenant    {args.tenant} (default brand, region {region})")
        print(f"player    {player} (random, so it has no progress)")
        print(f"open      {base}{prefix}/{PAGE_KEYS[0]}")
        print("pages     " + "  ".join(f"{base}{prefix}/{p}" for p in PAGE_KEYS[1:]))
    else:
        print(f"serving {skin.name} at {base}/<tenantId>/<playerId>/<page>")

    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(skin))
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            sys.exit(f"port {args.port} is already in use; pass --port with a free one, or stop what runs there")
        raise
    print(f"serving   {skin} (stop with Ctrl+C)", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
