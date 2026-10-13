"""Every command Kestrel understands, with a human description.

Used by the command palette (Ctrl+K), the menu, the help page and the
start page. Bindings in config.py map keys to these command strings.
"""

from __future__ import annotations

# (command, description, section, show in palette)
COMMANDS: list[tuple[str, str, str, bool]] = [
    ("tab-new", "New tab", "Tabs & windows", True),
    ("tab-close", "Close tab", "Tabs & windows", True),
    ("tab-undo", "Reopen closed tab", "Tabs & windows", True),
    ("tab-next", "Next tab", "Tabs & windows", True),
    ("tab-prev", "Previous tab", "Tabs & windows", True),
    ("tab-search", "Search open tabs", "Tabs & windows", True),
    ("tab-move -1", "Move tab left", "Tabs & windows", True),
    ("tab-move +1", "Move tab right", "Tabs & windows", True),
    ("tab-clone", "Duplicate tab", "Tabs & windows", True),
    ("tab-only", "Close other tabs", "Tabs & windows", True),
    ("window-new", "New window", "Tabs & windows", True),
    ("private", "New private window", "Tabs & windows", True),
    ("window-close", "Close window", "Tabs & windows", True),
    ("quit", "Quit Kestrel", "Tabs & windows", True),
    ("back", "Back", "Navigation", True),
    ("forward", "Forward", "Navigation", True),
    ("reload", "Reload", "Navigation", True),
    ("reload -f", "Reload, skipping the cache", "Navigation", True),
    ("stop", "Stop loading", "Navigation", True),
    ("home", "Home page", "Navigation", True),
    ("navigate up", "Go up one level in the URL", "Navigation", True),
    ("navigate root", "Go to the site's root", "Navigation", True),
    ("focus-url", "Focus the address bar", "Address bar", True),
    ("palette", "Command palette", "Address bar", False),
    ("bookmarks", "Search bookmarks", "Address bar", True),
    ("history", "Search history", "Address bar", True),
    ("paste", "Open the URL in the clipboard", "Address bar", True),
    ("paste -t", "Open the clipboard in a new tab", "Address bar", True),
    ("find", "Find in page", "Page", True),
    ("find-next", "Next match", "Page", False),
    ("find-prev", "Previous match", "Page", False),
    ("bookmark", "Bookmark this page", "Page", True),
    ("yank url", "Copy the page URL", "Page", True),
    ("yank title", "Copy the page title", "Page", True),
    ("hint", "Follow a link by typing its label", "Page", True),
    ("hint -t", "Open a link in a background tab", "Page", True),
    ("hint -y", "Copy a link's URL", "Page", True),
    ("focus-input", "Focus the first text field", "Page", True),
    ("zoom in", "Zoom in", "View", True),
    ("zoom out", "Zoom out", "View", True),
    ("zoom reset", "Reset zoom", "View", True),
    ("fullscreen", "Toggle fullscreen", "View", True),
    ("view-source", "View page source", "Tools", True),
    ("devtools", "Developer tools", "Tools", True),
    ("downloads", "Open the downloads folder", "Tools", True),
    ("config", "Edit settings (config.toml)", "Tools", True),
    ("theme-reload", "Reload the Omarchy theme", "Tools", True),
    ("help", "Keyboard shortcuts", "Tools", True),
    # Vim keymap only
    ("scroll down", "Scroll down", "Scrolling", False),
    ("scroll up", "Scroll up", "Scrolling", False),
    ("scroll left", "Scroll left", "Scrolling", False),
    ("scroll right", "Scroll right", "Scrolling", False),
    ("scroll-page 0.5", "Half page down", "Scrolling", False),
    ("scroll-page -0.5", "Half page up", "Scrolling", False),
    ("scroll-page 0.9", "Page down", "Scrolling", False),
    ("scroll-page -0.9", "Page up", "Scrolling", False),
    ("scroll-to top", "Top of page", "Scrolling", False),
    ("scroll-to bottom", "Bottom of page", "Scrolling", False),
    ("open", "Open URL or search", "Address bar", False),
    ("tab-new {url}", "Edit URL into a new tab", "Address bar", False),
    ("focus-url {url}", "Edit current URL", "Address bar", False),
    ("clear", "Clear search, hints and messages", "Page", False),
    ("mode insert", "Insert mode (type into the page)", "Modes", False),
    ("mode passthrough", "Passthrough mode (Shift+Esc leaves)", "Modes", False),
]

DESCRIPTIONS = {cmd: desc for cmd, desc, _, _ in COMMANDS}
SECTIONS = list(dict.fromkeys(section for _, _, section, _ in COMMANDS))
