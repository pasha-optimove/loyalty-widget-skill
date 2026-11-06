#!/usr/bin/env python3
from __future__ import annotations

import argparse
import colorsys
import json
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
MAX_BYTES = 3_000_000
MAX_STYLESHEETS = 20
SOURCE_SUFFIXES = {".css", ".scss", ".sass", ".less", ".html", ".htm", ".vue", ".svelte", ".jsx", ".tsx", ".astro", ".liquid", ".twig"}
SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".next", ".nuxt", "vendor", "coverage", ".venv", "__pycache__"}

COLOR_RE = re.compile(r"#[0-9a-fA-F]{8}\b|#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3,4}\b|rgba?\([^)]*\)|hsla?\([^)]*\)")
DECL_RE = re.compile(r"(--[\w-]+|[a-zA-Z-]+)\s*:\s*([^;{}]+)")
BLOCK_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
IMPORT_RE = re.compile(r"""@import\s+(?:url\()?\s*["']?([^"')\s;]+)""", re.IGNORECASE)
FONT_FACE_RE = re.compile(r"@font-face\s*\{[^}]*font-family\s*:\s*([^;}]+)", re.IGNORECASE)
VAR_RE = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^)]+))?\)")
GENERIC_FONTS = {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "inherit", "initial", "unset", "-apple-system", "blinkmacsystemfont", "ui-sans-serif", "ui-serif", "ui-monospace", "emoji"}


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.styles: list[str] = []
        self.inline: list[str] = []
        self.sheets: list[str] = []
        self.font_links: list[str] = []
        self.icons: list[str] = []
        self.logos: list[str] = []
        self.images: list[str] = []
        self.meta: dict[str, str] = {}
        self.title = ""
        self.headings: list[str] = []
        self.nav: list[str] = []
        self._stack: list[str] = []
        self._text: list[str] = []
        self._in_style = False
        self._in_title = False
        self._nav_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if a.get("style"):
            self.inline.append(a["style"])
        if tag == "style":
            self._in_style = True
        elif tag == "title":
            self._in_title = True
        elif tag == "link":
            rel, href = a.get("rel", "").lower(), a.get("href", "")
            if "fonts.googleapis.com" in href or "use.typekit.net" in href:
                self.font_links.append(href)
            elif "stylesheet" in rel and href:
                self.sheets.append(href)
            elif "icon" in rel and href:
                self.icons.append(href)
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or "").lower()
            if key in {"theme-color", "description", "og:site_name", "og:image", "og:title", "msapplication-tilecolor"}:
                self.meta[key] = a.get("content", "")
        elif tag in {"img", "svg"}:
            if tag == "img" and a.get("src") and not a["src"].startswith("data:"):
                self.images.append(a["src"])
            hint = " ".join(a.get(k, "") for k in ("src", "alt", "class", "id", "aria-label")).lower()
            if "logo" in hint or "brand" in hint:
                self.logos.append(a.get("src") or f"<{tag} class='{a.get('class', '')}'>")
        elif tag == "nav" or (tag == "header" and not self._nav_depth):
            self._nav_depth += 1
        if tag in {"h1", "h2", "h3", "a", "button"}:
            self._stack.append(tag)
            self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False
        elif tag == "title":
            self._in_title = False
        elif tag in {"nav", "header"} and self._nav_depth:
            self._nav_depth -= 1
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()
            text = re.sub(r"\s+", " ", "".join(self._text)).strip()
            if text and len(text) < 140:
                if tag in {"h1", "h2", "h3"}:
                    self.headings.append(text)
                elif self._nav_depth or tag == "button":
                    self.nav.append(text)

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.styles.append(data)
        elif self._in_title:
            self.title += data
        elif self._stack:
            self._text.append(data)


def fetch(url: str) -> tuple[str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/css,*/*"})
    with urllib.request.urlopen(req, timeout=20) as res:
        body = res.read(MAX_BYTES)
        charset = res.headers.get_content_charset() or "utf-8"
        return res.geturl(), body.decode(charset, errors="replace")


def to_hex(raw: str) -> str | None:
    raw = raw.strip().lower()
    if raw.startswith("#"):
        h = raw[1:]
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        if len(h) == 8:
            return f"#{h[:6]}" if h[6:] == "ff" else f"#{h[:6]}/{round(int(h[6:], 16) / 255, 2)}"
        return f"#{h}" if len(h) == 6 else None
    nums = re.findall(r"-?[\d.]+%?", raw)
    if len(nums) < 3:
        return None
    try:
        alpha = nums[3] if len(nums) > 3 else "1"
        a = float(alpha.rstrip("%")) / (100 if alpha.endswith("%") else 1)
        if raw.startswith("hsl"):
            h, s, light = float(nums[0]) / 360, float(nums[1].rstrip("%")) / 100, float(nums[2].rstrip("%")) / 100
            r, g, b = (round(v * 255) for v in colorsys.hls_to_rgb(h, light, s))
        else:
            r, g, b = (round(float(n.rstrip("%")) * (2.55 if n.endswith("%") else 1)) for n in nums[:3])
    except ValueError:
        return None
    base = "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, v)) for v in (r, g, b)))
    return base if a >= 1 else f"{base}/{round(a, 2)}"


def role_of(prop: str) -> str | None:
    if prop.startswith("background") or prop in {"fill"}:
        return "background"
    if prop == "color":
        return "text"
    if prop.startswith("border") or prop.startswith("outline"):
        return "border"
    if "shadow" in prop:
        return "shadow"
    return None


def first_family(value: str) -> str | None:
    for part in value.split(","):
        name = part.strip().strip("'\"").strip()
        if name and name.lower() not in GENERIC_FONTS and not name.startswith("var("):
            return name
    return None


def google_families(url: str) -> list[str]:
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    families = []
    for fam in query.get("family", []):
        for item in fam.split("|"):
            families.append(item.split(":")[0].replace("+", " "))
    return families


class Analysis:
    def __init__(self) -> None:
        self.vars: dict[str, str] = {}
        self.root_vars: set[str] = set()
        self.colors: Counter[str] = Counter()
        self.roles: dict[str, Counter[str]] = {"background": Counter(), "text": Counter(), "border": Counter()}
        self.fonts: Counter[str] = Counter()
        self.heading_fonts: Counter[str] = Counter()
        self.font_faces: Counter[str] = Counter()
        self.radii: Counter[str] = Counter()
        self.shadows: Counter[str] = Counter()
        self.google: list[str] = []
        self.css_bytes = 0

    def resolve(self, value: str, depth: int = 0) -> str:
        if depth > 5:
            return value
        return VAR_RE.sub(lambda m: self.resolve(self.vars.get(m.group(1), m.group(2) or ""), depth + 1), value)

    def add_css(self, css: str) -> None:
        self.css_bytes += len(css)
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
        for fam in FONT_FACE_RE.findall(css):
            name = first_family(fam)
            if name:
                self.font_faces[name] += 1
        for selector, body in BLOCK_RE.findall(css):
            is_root = bool(re.search(r"(^|[\s,]):root\b|(^|[\s,])html\b|(^|[\s,])body\b", selector))
            for prop, value in DECL_RE.findall(body):
                if prop.startswith("--"):
                    self.vars.setdefault(prop, value.strip())
                    if is_root:
                        self.root_vars.add(prop)
        for selector, body in BLOCK_RE.findall(css):
            heading = bool(re.search(r"\bh[1-3]\b|title|heading|display", selector, re.IGNORECASE))
            for prop, value in DECL_RE.findall(body):
                prop = prop.lower()
                if prop.startswith("--"):
                    continue
                self.add_decl(prop, value, heading)

    def add_decl(self, prop: str, value: str, heading: bool = False) -> None:
        value = self.resolve(value.strip())
        role = role_of(prop)
        if role or prop in {"stroke", "stop-color", "caret-color", "accent-color"}:
            for raw in COLOR_RE.findall(value):
                hexed = to_hex(raw)
                if hexed:
                    self.colors[hexed] += 1
                    if role in self.roles:
                        self.roles[role][hexed] += 1
        if prop in {"font-family", "font"}:
            if prop == "font-family":
                name = first_family(value)
            else:
                match = re.search(r"\d[\w.%]*(?:/[\w.%]+)?\s+(.+)$", value)
                name = first_family(match.group(1)) if match else None
            if name:
                self.fonts[name] += 1
                if heading:
                    self.heading_fonts[name] += 1
        elif prop == "border-radius" and value not in {"0", "0px", "inherit"}:
            self.radii[value] += 1
        elif prop == "box-shadow" and value != "none":
            self.shadows[value[:120]] += 1

    def add_inline(self, style: str) -> None:
        for prop, value in DECL_RE.findall(style):
            self.add_decl(prop.lower(), value)


def top(counter: Counter, n: int) -> list[dict]:
    return [{"value": k, "count": v} for k, v in counter.most_common(n)]


def from_url(url: str, analysis: Analysis) -> dict:
    final, html = fetch(url)
    page = PageParser()
    page.feed(html)
    fetched, failed = [], []
    queue = [urllib.parse.urljoin(final, h) for h in page.sheets]
    for css in page.styles:
        analysis.add_css(css)
        queue += [urllib.parse.urljoin(final, u) for u in IMPORT_RE.findall(css) if "fonts.googleapis" not in u]
        page.font_links += [u for u in IMPORT_RE.findall(css) if "fonts.googleapis" in u]
    seen: set[str] = set()
    while queue and len(fetched) < MAX_STYLESHEETS:
        sheet = queue.pop(0)
        if sheet in seen:
            continue
        seen.add(sheet)
        try:
            _, css = fetch(sheet)
        except Exception as e:
            failed.append(f"{sheet} ({e.__class__.__name__})")
            continue
        fetched.append(sheet)
        analysis.add_css(css)
        for imp in IMPORT_RE.findall(css):
            if "fonts.googleapis" in imp:
                page.font_links.append(imp)
            else:
                queue.append(urllib.parse.urljoin(sheet, imp))
    for style in page.inline:
        analysis.add_inline(style)
    for link in page.font_links:
        analysis.google += google_families(link)
    absolute = lambda items: [urllib.parse.urljoin(final, i) if not i.startswith("<") else i for i in dict.fromkeys(items)]
    return {
        "source": final,
        "title": page.title.strip(),
        "meta": page.meta,
        "logos": absolute(page.logos)[:6],
        "icons": absolute(page.icons)[:4],
        "images": absolute(page.images)[:8],
        "fontLinks": list(dict.fromkeys(page.font_links)),
        "headings": list(dict.fromkeys(page.headings))[:20],
        "navAndButtons": list(dict.fromkeys(page.nav))[:20],
        "stylesheets": {"read": fetched, "failed": failed},
    }


STYLE_OR_SCRIPT_RE = re.compile(r"<(style|script)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")


def add_color_literals(text: str, analysis: Analysis) -> None:
    analysis.add_inline(";".join(f"color:{c}" for c in COLOR_RE.findall(text)))


def add_text(text: str, name: str, analysis: Analysis, page: PageParser, themes: list[dict]) -> None:
    suffix = Path(name).suffix.lower()
    if name.startswith("tailwind.config") or suffix == ".json":
        themes.append({"file": name, "excerpt": text[:4000]})
        add_color_literals(text, analysis)
    elif suffix in {".css", ".scss", ".sass", ".less"}:
        analysis.add_css(text)
    elif suffix in SOURCE_SUFFIXES:
        if suffix not in {".html", ".htm"}:
            add_color_literals(text, analysis)
        page.feed(text)
        for css in page.styles:
            analysis.add_css(css)
        page.styles = []
    else:
        page.feed(text)
        for css in page.styles:
            analysis.add_css(css)
        page.styles = []
        rest = TAG_RE.sub(" ", STYLE_OR_SCRIPT_RE.sub(" ", text))
        analysis.add_css(rest)
        missed = [c for c in COLOR_RE.findall(rest) if to_hex(c) and to_hex(c) not in analysis.colors]
        add_color_literals(" ".join(missed), analysis)
        looks_like_css = re.search(r"[^{}]+\{[^{}]*:[^{}]*;", rest)
        looks_like_config = "{" in rest and COLOR_RE.search(rest) and re.search(r"\b(theme|colou?rs?|palette|tokens?|value|primary|brand)\b", rest, re.IGNORECASE)
        if looks_like_config and not looks_like_css:
            themes.append({"file": name, "excerpt": rest.strip()[:4000]})


def from_text(text: str, label: str, analysis: Analysis) -> dict:
    page = PageParser()
    themes: list[dict] = []
    add_text(text, "pasted", analysis, page, themes)
    for style in page.inline:
        analysis.add_inline(style)
    for link in page.font_links:
        analysis.google += google_families(link)
    return {
        "source": label,
        "title": page.title.strip(),
        "meta": page.meta,
        "logos": list(dict.fromkeys(page.logos))[:6],
        "icons": list(dict.fromkeys(page.icons))[:4],
        "images": list(dict.fromkeys(page.images))[:8],
        "fontLinks": list(dict.fromkeys(page.font_links)),
        "headings": list(dict.fromkeys(page.headings))[:20],
        "navAndButtons": list(dict.fromkeys(page.nav))[:20],
        "themeFiles": themes[:4],
        "charactersRead": len(text),
    }


def from_path(path: Path, analysis: Analysis) -> dict:
    files = [path] if path.is_file() else [
        p for p in path.rglob("*")
        if p.is_file() and not (SKIP_DIRS & set(p.relative_to(path).parts))
        and (p.suffix.lower() in SOURCE_SUFFIXES or re.match(r"(tailwind\.config|theme|tokens|colors|palette)\b", p.name, re.IGNORECASE))
    ]
    page = PageParser()
    tailwind = []
    read = []
    for f in files[:800]:
        try:
            text = f.read_text(errors="replace")[:MAX_BYTES]
        except OSError:
            continue
        read.append(str(f))
        add_text(text, f.name, analysis, page, tailwind)
    for style in page.inline:
        analysis.add_inline(style)
    for link in page.font_links:
        analysis.google += google_families(link)
    return {
        "source": str(path),
        "title": page.title.strip(),
        "meta": page.meta,
        "logos": list(dict.fromkeys(page.logos))[:6],
        "icons": list(dict.fromkeys(page.icons))[:4],
        "images": list(dict.fromkeys(page.images))[:8],
        "fontLinks": list(dict.fromkeys(page.font_links)),
        "headings": list(dict.fromkeys(page.headings))[:20],
        "navAndButtons": list(dict.fromkeys(page.nav))[:20],
        "themeFiles": tailwind[:4],
        "filesRead": len(read),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read a brand's design tokens from a website's source, a local folder, or pasted code, without a browser.")
    parser.add_argument("source", help="https:// URL; a local file or folder (site repo, theme, token export); or - to read pasted code from stdin")
    args = parser.parse_args()
    analysis = Analysis()
    is_url = re.match(r"^https?://", args.source)
    if args.source == "-":
        text = sys.stdin.read()
        if not text.strip():
            sys.exit("Nothing was pasted on stdin")
        report = from_text(text[:MAX_BYTES], "pasted code", analysis)
    elif is_url:
        report = from_url(args.source, analysis)
    elif Path(args.source).expanduser().exists():
        report = from_path(Path(args.source).expanduser(), analysis)
    else:
        sys.exit(f"{args.source} is neither an http(s) URL, an existing file or folder, nor - for pasted code")

    colorish = {k: v for k, v in analysis.vars.items() if COLOR_RE.search(analysis.resolve(v))}
    ordered = sorted(analysis.vars, key=lambda k: (k not in analysis.root_vars, k not in colorish))
    report["customProperties"] = {k: analysis.vars[k] for k in ordered[:80]}
    report["colors"] = {
        "overall": top(analysis.colors, 16),
        "background": top(analysis.roles["background"], 8),
        "text": top(analysis.roles["text"], 8),
        "border": top(analysis.roles["border"], 6),
    }
    report["fonts"] = {
        "googleFonts": list(dict.fromkeys(analysis.google)),
        "fontFace": top(analysis.font_faces, 8),
        "usedInCss": top(analysis.fonts, 8),
        "headings": top(analysis.heading_fonts, 4),
    }
    report["radii"] = top(analysis.radii, 6)
    report["shadows"] = top(analysis.shadows, 4)
    warnings = []
    if len(analysis.colors) < 4:
        if args.source == "-":
            warnings.append("Very little styling found in the pasted code. Ask for the site's CSS files, its design tokens or theme config, or a brandbook.")
        elif is_url:
            warnings.append("Very little styling found in the source. The site probably builds its look with JavaScript at runtime; ask the user to paste the page's rendered code or its CSS, or read it in a browser if one is available.")
        else:
            warnings.append("Very little styling found in these files. The look probably comes from a theme API, a design-token package or utility classes; point this at the token files or ask for a brandbook.")
    if is_url and report["stylesheets"]["failed"]:
        warnings.append("Some stylesheets could not be read; colors and fonts may be incomplete.")
    report["warnings"] = warnings
    json.dump(report, sys.stdout, indent=1, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
