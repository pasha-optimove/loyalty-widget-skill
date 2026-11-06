#!/usr/bin/env python3
import argparse
import http.server
from pathlib import Path


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve a widget skin on every path, the way the widget host does.")
    parser.add_argument("skin", type=Path)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    skin = args.skin.resolve()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(skin))
    print(f"serving {skin.name} at http://localhost:{args.port}/<tenantId>/brand/<brandName>/<playerId>/<page>")
    server.serve_forever()


if __name__ == "__main__":
    main()
