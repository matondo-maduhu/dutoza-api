#!/usr/bin/env python3
"""
Jenereta ya CSS ya mode ya giza.

Inasoma <style> zote za templates za watumiaji, na kwa kila sheria yenye rangi
inatengeneza toleo la giza chini ya  html[data-theme="dark"] ...
Matokeo yanakwenda static/css/dark/<ukurasa>.css

Endesha tena kila ukibadilisha rangi kwenye templates:
    python3 tools/gen_dark.py
"""

import colorsys
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(ROOT, "templates", "users")
OUT = os.path.join(ROOT, "static", "css", "dark")

PAGES = {
    "base": "base.html",
    "feed": "feed.html",
    "profile": "profile.html",
    "search": "search.html",
    "settings": "settings.html",
    "public_profile": "public_profile.html",
    "music_composer": "music_composer.html",
    "login": "login.html",
    "register": "register.html",
    "static_page": "static_page.html",
}

DARK_BG_TINT_HUE = 222 / 360      # rangi ya samawati-nyeusi ya mandharinyuma

# (L ya mwanga) -> (L ya giza) kwa mandharinyuma za rangi isiyo na chroma (neutral)
BG_TABLE = [
    (1.000, 0.115), (0.975, 0.095), (0.960, 0.070), (0.940, 0.120),
    (0.900, 0.185), (0.800, 0.260), (0.650, 0.340), (0.500, 0.400),
]
BORDER_TABLE = [
    (1.000, 0.200), (0.940, 0.185), (0.900, 0.210), (0.800, 0.270), (0.650, 0.330), (0.500, 0.400),
]

COLOR_RE = re.compile(
    r"#[0-9a-fA-F]{8}\b|#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3,4}\b|rgba?\([^)]*\)|\bwhite\b|\bblack\b",
    re.I,
)

BG_PROPS = {"background", "background-color", "background-image"}
FG_PROPS = {"color", "fill", "stroke", "caret-color", "text-decoration-color", "accent-color"}
BORDER_PREFIXES = ("border", "outline")
SHADOW_PROPS = {"box-shadow", "text-shadow", "filter", "drop-shadow"}


# ---------------------------------------------------------------- rangi
def parse_color(token):
    t = token.strip().lower()

    if t == "white":
        return (255, 255, 255, 1.0)
    if t == "black":
        return (0, 0, 0, 1.0)

    if t.startswith("#"):
        h = t[1:]
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        return (r, g, b, a)

    m = re.match(r"rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.%]+))?\s*\)", t)
    if m:
        a = m.group(4)
        if a is None:
            alpha = 1.0
        elif a.endswith("%"):
            alpha = float(a[:-1]) / 100
        else:
            alpha = float(a)
        return (float(m.group(1)), float(m.group(2)), float(m.group(3)), alpha)

    return None


def fmt(rgb, alpha):
    r, g, b = [max(0, min(255, int(round(v)))) for v in rgb]

    if alpha >= 0.999:
        return "#%02x%02x%02x" % (r, g, b)

    return "rgba(%d,%d,%d,%s)" % (r, g, b, ("%.3f" % alpha).rstrip("0").rstrip("."))


def piecewise(table, value):
    for (x1, y1), (x2, y2) in zip(table, table[1:]):
        if value <= x1 and value >= x2:
            u = (value - x2) / (x1 - x2) if x1 != x2 else 0
            return y2 + (y1 - y2) * u

    return table[-1][1] if value < table[-1][0] else table[0][1]


def hls(rgb):
    r, g, b = [v / 255 for v in rgb]
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    chroma = max(r, g, b) - min(r, g, b)
    return h, l, s, chroma


def from_hls(h, l, s):
    r, g, b = colorsys.hls_to_rgb(h, max(0, min(1, l)), max(0, min(1, s)))
    return (r * 255, g * 255, b * 255)


def transform(token, kind):
    parsed = parse_color(token)

    if not parsed:
        return token

    r, g, b, a = parsed
    h, l, s, chroma = hls((r, g, b))
    neutral = chroma < 0.05 or (0.55 <= h <= 0.70 and chroma < 0.26)

    if kind == "shadow":
        if l > 0.9:
            return fmt((0, 0, 0), max(a, 0.45) if a < 1 else 0.5)
        return token

    if kind == "bg":
        if neutral:
            if l >= 0.5:
                nl = piecewise(BG_TABLE, l)
                return fmt(from_hls(DARK_BG_TINT_HUE, nl, 0.30), a)
            return token                                  # tayari giza (mfano #0f172a)
        if l > 0.80:                                      # pastel -> giza yenye rangi
            return fmt(from_hls(h, 0.15 + (1 - l) * 0.35, min(s, 0.40)), a)
        if l > 0.58:
            return fmt(from_hls(h, 0.30, min(s, 0.45)), a)
        return token                                      # rangi kali (brand) inabaki

    if kind == "border":
        if neutral:
            if l >= 0.5:
                return fmt(from_hls(DARK_BG_TINT_HUE, piecewise(BORDER_TABLE, l), 0.28), a)
            return token
        if l > 0.70:
            return fmt(from_hls(h, 0.27, min(s, 0.45)), a)
        return token

    if kind == "fg":
        if neutral:
            if l >= 0.88:
                return token                              # maandishi meupe yanabaki meupe
            if l >= 0.62:
                return token                              # kijivu hafifu kinabaki
            nl = min(0.93 - 0.70 * l, 0.93)
            return fmt(from_hls(DARK_BG_TINT_HUE, nl, 0.18), a)
        if l < 0.60:                                      # maandishi ya rangi yaliyo meusi -> angavu
            return fmt(from_hls(h, 0.62 + (0.60 - l) * 0.25, min(max(s, 0.55), 0.90)), a)
        return token

    return token


def transform_value(prop, value):
    p = prop.lower()

    if p in BG_PROPS:
        kind = "bg"
    elif p in FG_PROPS:
        kind = "fg"
    elif p.startswith(BORDER_PREFIXES):
        kind = "border"
    elif p in SHADOW_PROPS:
        kind = "shadow"
    else:
        return None

    if not COLOR_RE.search(value):
        return None

    new = COLOR_RE.sub(lambda m: transform(m.group(0), kind), value)

    return new if new != value else None


# ---------------------------------------------------------------- CSS parser
def strip_templating(css):
    css = re.sub(r"\{%.*?%\}", "", css, flags=re.S)
    css = re.sub(r"\{\{.*?\}\}", "0", css, flags=re.S)
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return css


def split_blocks(css):
    """Gawa CSS kuwa [(prelude, body)] ya ngazi ya juu."""
    blocks, depth, start, prelude_start = [], 0, 0, 0

    for i, ch in enumerate(css):
        if ch == "{":
            if depth == 0:
                prelude = css[prelude_start:i].strip()
                start = i + 1
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blocks.append((prelude, css[start:i]))
                prelude_start = i + 1

    return blocks


def split_declarations(body):
    out, depth, cur = [], 0, ""

    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1

        if ch == ";" and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch

    if cur.strip():
        out.append(cur)

    return out


def prefix_selector(selector):
    selector = selector.strip()

    if not selector or selector.startswith(":root"):
        return None

    if selector == "html":
        return 'html[data-theme="dark"]'

    if selector.startswith("html "):
        return 'html[data-theme="dark"] ' + selector[5:]

    return 'html[data-theme="dark"] ' + selector


def convert_rule(selectors, body):
    declarations = []

    for decl in split_declarations(body):
        if ":" not in decl:
            continue

        prop, value = decl.split(":", 1)
        new_value = transform_value(prop.strip(), value.strip().rstrip(";"))

        if new_value:
            declarations.append("%s: %s" % (prop.strip(), new_value))

    if not declarations:
        return ""

    prefixed = [prefix_selector(s) for s in selectors.split(",")]
    prefixed = [s for s in prefixed if s]

    if not prefixed:
        return ""

    return "%s { %s; }\n" % (",\n".join(prefixed), "; ".join(declarations))


def convert_css(css):
    out = []

    for prelude, body in split_blocks(strip_templating(css)):
        if prelude.startswith("@media") or prelude.startswith("@supports"):
            inner = convert_css(body)

            if inner.strip():
                out.append("%s {\n%s}\n" % (prelude, inner))

        elif prelude.startswith("@"):
            continue                                       # @keyframes, @font-face n.k.
        else:
            out.append(convert_rule(prelude, body))

    return "".join(out)


def extract_styles(html):
    parts = re.findall(r"<style[^>]*>(.*?)</style>", html, flags=re.S | re.I)
    parts += re.findall(r"\{%\s*block\s+extra_css\s*%\}(.*?)\{%\s*endblock\s*%\}", html, flags=re.S)
    return "\n".join(parts)


def main():
    os.makedirs(OUT, exist_ok=True)
    total = 0

    for name, filename in PAGES.items():
        path = os.path.join(TEMPLATES, filename)

        with open(path, encoding="utf-8") as handle:
            css = convert_css(extract_styles(handle.read()))

        header = "/* Imetengenezwa na tools/gen_dark.py kutoka templates/users/%s - usihariri kwa mkono. */\n" % filename

        with open(os.path.join(OUT, name + ".css"), "w", encoding="utf-8") as handle:
            handle.write(header + css)

        total += len(css)
        print("%-16s %6d bytes" % (name, len(css)))

    print("jumla: %d bytes" % total)


if __name__ == "__main__":
    main()
