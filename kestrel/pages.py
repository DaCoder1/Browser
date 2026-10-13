"""HTML for the built-in kestrel:// pages."""

from __future__ import annotations

from html import escape

from kestrel.theme import Palette

HELP_SECTIONS = [
    ("Scrolling", ["scroll", "scroll-page", "scroll-to"]),
    ("Navigation", ["back", "forward", "reload", "navigate", "home", "view-source", "clear"]),
    ("Opening", ["set-cmd open", "paste"]),
    ("Tabs", ["tab-", "set-cmd buffer"]),
    ("Hints & input", ["hint", "focus-input", "mode"]),
    ("Clipboard & search", ["yank", "set-cmd /", "search-"]),
    ("Zoom", ["zoom"]),
    ("Other", [""]),
]

DESCRIPTIONS = {
    "scroll down": "scroll down", "scroll up": "scroll up",
    "scroll left": "scroll left", "scroll right": "scroll right",
    "scroll-page 0.5": "half page down", "scroll-page -0.5": "half page up",
    "scroll-page 0.9": "page down", "scroll-page -0.9": "page up",
    "scroll-to top": "top of page", "scroll-to bottom": "bottom of page",
    "back": "history back", "forward": "history forward",
    "reload": "reload", "reload -f": "reload, bypass cache",
    "navigate up": "go up one URL level", "navigate root": "go to site root",
    "view-source": "view page source", "clear": "clear search / hints / messages",
    "home": "open start page",
    "set-cmd open ": "open URL or search", "set-cmd open -t ": "open in new tab",
    "set-cmd open {url}": "edit current URL", "set-cmd open -t {url}": "edit URL into new tab",
    "paste": "open clipboard", "paste -t": "open clipboard in new tab",
    "tab-next": "next tab", "tab-prev": "previous tab", "tab-close": "close tab",
    "tab-undo": "reopen closed tab", "tab-clone": "duplicate tab",
    "tab-move -1": "move tab left", "tab-move +1": "move tab right",
    "tab-focus 1": "first tab", "tab-focus -1": "last tab",
    "set-cmd buffer ": "fuzzy-pick an open tab",
    "hint": "follow link", "hint -t": "open link in new tab", "hint -y": "copy link URL",
    "focus-input": "focus first input", "mode insert": "insert mode (type into page)",
    "mode passthrough": "passthrough mode (all keys to page, Shift+Esc exits)",
    "yank url": "copy URL", "yank title": "copy title",
    "set-cmd /": "find in page", "search-next": "next match", "search-prev": "previous match",
    "zoom in": "zoom in", "zoom out": "zoom out", "zoom reset": "reset zoom",
    "bookmark": "toggle bookmark", "help": "this page", "devtools": "developer tools",
    "quit": "quit (saves session)", "quit --no-save": "quit without saving session",
    "set-cmd ": "command line",
}


def _css(p: Palette, font: str) -> str:
    return f"""
    :root {{ color-scheme: {'light' if p.is_light else 'dark'}; }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; background: {p.bg}; color: {p.fg};
      font: 15px/1.5 '{font}', 'JetBrains Mono', monospace; }}
    a {{ color: {p.accent}; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    kbd {{ display: inline-block; min-width: 1.6em; text-align: center; padding: 0 .4em;
      border: 1px solid {p.muted}; border-bottom-width: 2px; border-radius: 4px;
      color: {p.yellow}; background: {p.bg_alt}; font: inherit; font-size: 13px; }}
    .muted {{ color: {p.muted}; }}
    """


def start_page(p: Palette, font: str, top: list[tuple[str, str]], bookmarks: list[tuple[str, str]]) -> str:
    def items(rows):
        if not rows:
            return '<li class="muted">nothing yet</li>'
        return "".join(
            f'<li><a href="{escape(u, True)}">{escape(t or u)}</a>'
            f'<span class="muted url">{escape(u)}</span></li>'
            for u, t in rows
        )

    keys = [
        ("o", "open / search"), ("t", "new tab"), ("f", "follow link"),
        ("j k", "scroll"), ("H L", "back / fwd"), ("J K", "switch tab"),
        ("x", "close tab"), ("b", "pick tab"), ("/", "find"), ("?", "all keys"),
    ]
    keyhtml = "".join(f"<div><kbd>{escape(k).replace(' ', '</kbd> <kbd>')}</kbd> <span>{d}</span></div>" for k, d in keys)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>New Tab</title>
<style>{_css(p, font)}
  main {{ max-width: 920px; margin: 0 auto; padding: 9vh 32px 48px; }}
  h1 {{ font-size: 44px; margin: 0; letter-spacing: -1px; font-weight: 700; }}
  h1 span {{ color: {p.accent}; }}
  .tag {{ color: {p.muted}; margin: 4px 0 36px; }}
  .prompt {{ border: 1px solid {p.line}; background: {p.bg_alt}; border-radius: 8px;
    padding: 14px 18px; color: {p.muted}; }}
  .prompt b {{ color: {p.accent}; }}
  .keys {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px 18px;
    margin: 28px 0 40px; font-size: 13px; }}
  .keys span {{ color: {p.fg}; opacity: .8; }}
  .cols {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 40px; }}
  h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: 2px; color: {p.magenta};
    margin: 0 0 12px; font-weight: 600; }}
  ul {{ list-style: none; margin: 0; padding: 0; }}
  li {{ padding: 6px 0; border-bottom: 1px solid {p.line}; overflow: hidden;
    white-space: nowrap; text-overflow: ellipsis; }}
  .url {{ margin-left: 10px; font-size: 12px; }}
  @media (max-width: 700px) {{ .keys {{ grid-template-columns: repeat(2, 1fr); }} .cols {{ grid-template-columns: minmax(0, 1fr); }} }}
</style></head><body><main>
  <h1>kestrel<span>.</span></h1>
  <div class="tag">keyboard-driven browsing for omarchy &middot; theme: {escape(p.name)}</div>
  <div class="prompt"><kbd>o</kbd>&nbsp; type a URL or search &mdash; prefix with <b>yt</b>&#8202;/&#8202;<b>gh</b>&#8202;/&#8202;<b>aw</b>&#8202;/&#8202;<b>w</b>&#8202;/&#8202;<b>g</b> to pick an engine</div>
  <div class="keys">{keyhtml}</div>
  <div class="cols">
    <section><h2>Bookmarks</h2><ul>{items(bookmarks)}</ul></section>
    <section><h2>Frequent</h2><ul>{items(top)}</ul></section>
  </div>
</main></body></html>"""


def help_page(p: Palette, font: str, bindings: dict[str, str], engines: dict[str, str]) -> str:
    by_cmd: dict[str, list[str]] = {}
    for key, cmd in bindings.items():
        by_cmd.setdefault(cmd, []).append(key)
    used: set[str] = set()
    sections = []
    for title, prefixes in HELP_SECTIONS:
        rows = []
        for cmd, keys in by_cmd.items():
            if cmd in used or not any(cmd.startswith(px) for px in prefixes):
                continue
            if cmd.startswith("tab-focus") and cmd not in ("tab-focus 1", "tab-focus -1"):
                continue
            used.add(cmd)
            kb = " ".join(f"<kbd>{escape(k)}</kbd>" for k in keys)
            rows.append(f"<tr><td>{kb}</td><td>{escape(DESCRIPTIONS.get(cmd, cmd))}</td></tr>")
        if title == "Tabs":
            rows.append("<tr><td><kbd>&lt;A-1&gt;</kbd>&hellip;<kbd>&lt;A-9&gt;</kbd></td><td>jump to tab N</td></tr>")
        if rows:
            sections.append(f"<section><h2>{title}</h2><table>{''.join(rows)}</table></section>")
    eng = "".join(f"<tr><td><kbd>{escape(k)}</kbd></td><td class='muted'>{escape(v)}</td></tr>" for k, v in engines.items())
    commands = (
        "open [-t] URL|search · tab-close · tab-undo · buffer N|text · bookmark · "
        "zoom in|out|reset|N · yank url|title · reload [-f] · devtools · help · quit"
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Kestrel help</title>
<style>{_css(p, font)}
  main {{ max-width: 1100px; margin: 0 auto; padding: 40px 32px; }}
  h1 {{ margin: 0 0 4px; }} h1 span {{ color: {p.accent}; }}
  .grid {{ columns: 2 420px; column-gap: 40px; margin-top: 24px; }}
  section {{ break-inside: avoid; margin-bottom: 26px; }}
  h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: 2px; color: {p.magenta}; margin: 0 0 8px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  td {{ padding: 4px 8px 4px 0; border-bottom: 1px solid {p.line}; vertical-align: top; }}
  td:first-child {{ width: 45%; }}
  code {{ color: {p.green}; }}
</style></head><body><main>
  <h1>kestrel<span>.</span> keys</h1>
  <div class="muted">Modes: <b style="color:{p.accent}">NORMAL</b> (keys are commands) ·
    <b style="color:{p.green}">INSERT</b> (typing goes to page, <kbd>Esc</kbd> leaves) ·
    <b style="color:{p.yellow}">HINT</b> · <b style="color:{p.magenta}">COMMAND</b> ·
    <b style="color:{p.red}">PASSTHROUGH</b> (<kbd>Shift+Esc</kbd> leaves).
    Prefix most keys with a count, e.g. <kbd>5</kbd><kbd>j</kbd>.
    Remap keys in <code>~/.config/kestrel/config.toml</code>.</div>
  <div class="grid">{''.join(sections)}
    <section><h2>Search engines</h2><table>{eng}</table></section>
    <section><h2>Commands (type after <kbd>:</kbd>)</h2><p class="muted">{commands}</p></section>
  </div>
</main></body></html>"""
