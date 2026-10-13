"""HTML for the built-in kestrel:// pages."""

from __future__ import annotations

from html import escape

from kestrel.commands import COMMANDS, DESCRIPTIONS, SECTIONS
from kestrel.config import Config
from kestrel.keys import pretty_key
from kestrel.theme import Palette

START_KEYS = ["focus-url", "tab-new", "tab-search", "palette", "find", "hint",
              "bookmark", "tab-undo", "private", "help"]
VIM_START_KEYS = ["open", "tab-new", "hint", "scroll down", "back", "tab-next",
                  "tab-close", "tab-search", "find", "help"]


def keys_for(cfg: Config, cmd: str) -> list[str]:
    vim = cfg.keymap == "vim"
    keys = [k for k, c in cfg.bindings.items() if c == cmd]
    keys.sort(key=lambda k: k.startswith("<") == vim)  # stable: keeps config order
    return keys


def kbd(key: str) -> str:
    if len(key) > 1 and key.startswith("<"):
        pretty = pretty_key(key)
        parts = pretty[:-2].split("+") + ["+"] if pretty.endswith("++") else pretty.split("+")
        return "".join(f"<kbd>{escape(part)}</kbd>" for part in parts)
    return f"<kbd>{escape(key)}</kbd>"


def _css(p: Palette, font: str) -> str:
    return f"""
    :root {{ color-scheme: {'light' if p.is_light else 'dark'}; }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; background: {p.bg}; color: {p.fg};
      font: 15px/1.5 '{font}', 'JetBrains Mono', monospace; }}
    a {{ color: {p.accent}; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    kbd {{ display: inline-block; min-width: 1.6em; text-align: center; padding: 0 .4em; margin-right: 2px;
      border: 1px solid {p.muted}; border-bottom-width: 2px; border-radius: 4px;
      color: {p.yellow}; background: {p.bg_alt}; font: inherit; font-size: 12px; }}
    .muted {{ color: {p.muted}; }}
    """


def start_page(p: Palette, cfg: Config, top: list[tuple[str, str]], bookmarks: list[tuple[str, str]]) -> str:
    def items(rows):
        if not rows:
            return '<li class="muted">nothing yet</li>'
        return "".join(
            f'<li><a href="{escape(u, True)}">{escape(t or u)}</a>'
            f'<span class="muted url">{escape(u)}</span></li>'
            for u, t in rows
        )

    cmds = VIM_START_KEYS if cfg.keymap == "vim" else START_KEYS
    keyhtml = ""
    for cmd in cmds:
        keys = keys_for(cfg, cmd)
        if keys:
            keyhtml += f"<div>{kbd(keys[0])} <span>{escape(DESCRIPTIONS.get(cmd, cmd))}</span></div>"
    url_keys = keys_for(cfg, "open" if cfg.keymap == "vim" else "focus-url")
    url_key = kbd(url_keys[0]) if url_keys else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>New Tab</title>
<style>{_css(p, cfg.font)}
  main {{ max-width: 920px; margin: 0 auto; padding: 9vh 32px 48px; }}
  h1 {{ font-size: 44px; margin: 0; letter-spacing: -1px; font-weight: 700; }}
  h1 span {{ color: {p.accent}; }}
  .tag {{ color: {p.muted}; margin: 4px 0 30px; }}
  .tip {{ border: 1px solid {p.line}; background: {p.bg_alt}; border-radius: 10px;
    padding: 14px 18px; color: {p.muted}; }}
  .tip b {{ color: {p.accent}; font-weight: 600; }}
  .keys {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 40px;
    margin: 24px 0 40px; font-size: 13px; }}
  .keys span {{ color: {p.fg}; opacity: .85; margin-left: 4px; }}
  .cols {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 40px; }}
  h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: 2px; color: {p.magenta};
    margin: 0 0 12px; font-weight: 600; }}
  ul {{ list-style: none; margin: 0; padding: 0; }}
  li {{ padding: 6px 0; border-bottom: 1px solid {p.line}; overflow: hidden;
    white-space: nowrap; text-overflow: ellipsis; }}
  .url {{ margin-left: 10px; font-size: 12px; }}
  @media (max-width: 700px) {{ .keys, .cols {{ grid-template-columns: minmax(0, 1fr); }} }}
</style></head><body><main>
  <h1>kestrel<span>.</span></h1>
  <div class="tag">a keyboard-friendly browser for omarchy &middot; theme: {escape(p.name)}</div>
  <div class="tip">{url_key} type an address or search &middot; start with
    <b>yt</b>&#8202;/&#8202;<b>gh</b>&#8202;/&#8202;<b>aw</b>&#8202;/&#8202;<b>w</b> to pick an engine,
    <b>&gt;</b> for commands, <b>%</b> for open tabs</div>
  <div class="keys">{keyhtml}</div>
  <div class="cols">
    <section><h2>Bookmarks</h2><ul>{items(bookmarks)}</ul></section>
    <section><h2>Frequent</h2><ul>{items(top)}</ul></section>
  </div>
</main></body></html>"""


def help_page(p: Palette, cfg: Config) -> str:
    vim = cfg.keymap == "vim"
    sections = []
    for section in SECTIONS:
        rows = []
        for cmd, desc, sec, _ in COMMANDS:
            if sec != section:
                continue
            keys = keys_for(cfg, cmd)
            if not keys:
                continue
            kb = " &nbsp;".join(kbd(k) for k in keys[:2])
            rows.append(f"<tr><td>{escape(desc)}</td><td>{kb}</td></tr>")
        if section == "Tabs & windows":
            jump = "<kbd>Ctrl</kbd><kbd>1</kbd>…<kbd>8</kbd> &nbsp;<kbd>Alt</kbd><kbd>1</kbd>…<kbd>9</kbd>"
            rows.insert(5, f"<tr><td>Jump to tab 1–9</td><td>{jump}</td></tr>")
        if rows:
            sections.append(f"<section><h2>{escape(section)}</h2><table>{''.join(rows)}</table></section>")
    prefixes = (
        "<tr><td>Run a command</td><td><kbd>&gt;</kbd> zoom, private…</td></tr>"
        "<tr><td>Switch to an open tab</td><td><kbd>%</kbd> title or URL</td></tr>"
        "<tr><td>Search bookmarks</td><td><kbd>*</kbd></td></tr>"
        "<tr><td>Search history</td><td><kbd>^</kbd></td></tr>"
        "<tr><td>Open in a new tab</td><td><kbd>Alt</kbd><kbd>Enter</kbd></td></tr>"
    )
    sections.append(f"<section><h2>Address bar tricks</h2><table>{prefixes}</table></section>")
    eng = "".join(f"<tr><td class='muted'>{escape(v)}</td><td><kbd>{escape(k)}</kbd></td></tr>"
                  for k, v in cfg.search_engines.items())
    sections.append(f"<section><h2>Search shortcuts</h2><table>{eng}</table></section>")
    if vim:
        intro = (
            f"Vim keymap: <b style='color:{p.accent}'>NORMAL</b> mode runs commands, "
            f"<b style='color:{p.green}'>INSERT</b> types into the page (<kbd>Esc</kbd> leaves), "
            f"<b style='color:{p.red}'>PASSTHROUGH</b> sends every key to the page "
            "(<kbd>Shift</kbd><kbd>Esc</kbd> leaves). Prefix keys with a count, e.g. <kbd>5</kbd><kbd>j</kbd>."
        )
    else:
        intro = (
            "Typing always goes to the page. Shortcuts work everywhere, even in text fields. "
            "Set <code>keymap = \"vim\"</code> for modal Vim keys."
        )
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Keyboard shortcuts</title>
<style>{_css(p, cfg.font)}
  main {{ max-width: 1100px; margin: 0 auto; padding: 40px 32px; }}
  h1 {{ margin: 0 0 6px; }} h1 span {{ color: {p.accent}; }}
  .grid {{ columns: 2 420px; column-gap: 48px; margin-top: 26px; }}
  section {{ break-inside: avoid; margin-bottom: 26px; }}
  h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: 2px; color: {p.magenta}; margin: 0 0 8px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  td {{ padding: 5px 8px 5px 0; border-bottom: 1px solid {p.line}; vertical-align: top; }}
  td:last-child {{ text-align: right; white-space: nowrap; }}
  code {{ color: {p.green}; }}
</style></head><body><main>
  <h1>keyboard shortcuts<span>.</span></h1>
  <div class="muted">{intro} Remap anything in <code>~/.config/kestrel/config.toml</code>.</div>
  <div class="grid">{''.join(sections)}</div>
</main></body></html>"""
