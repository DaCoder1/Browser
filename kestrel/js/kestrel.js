// Kestrel helper library. Runs in an isolated JS world, so page scripts
// cannot see or tamper with it (they still share the DOM).
(function () {
  "use strict";
  if (window.__kestrel) return;

  const EDITABLE_INPUT_TYPES = new Set([
    "", "text", "search", "email", "url", "tel", "password", "number",
    "date", "datetime-local", "month", "time", "week",
  ]);

  function deepActiveElement() {
    let el = document.activeElement;
    while (el && el.shadowRoot && el.shadowRoot.activeElement) {
      el = el.shadowRoot.activeElement;
    }
    return el;
  }

  function isEditable(el) {
    if (!el) return false;
    if (el.isContentEditable) return true;
    const tag = el.tagName;
    if (tag === "TEXTAREA") return !el.readOnly && !el.disabled;
    if (tag === "SELECT") return true;
    if (tag === "INPUT") {
      return EDITABLE_INPUT_TYPES.has((el.getAttribute("type") || "").toLowerCase())
        && !el.readOnly && !el.disabled;
    }
    // Cross-origin iframes keep focus on the <iframe> element itself.
    if (tag === "IFRAME" || tag === "EMBED" || tag === "OBJECT") return true;
    return false;
  }

  // ---- Mode notifications --------------------------------------------------
  // The browser listens for these console messages. Only user clicks switch
  // modes, so pages that autofocus their search box don't steal the keyboard.
  document.addEventListener("mousedown", function () {
    setTimeout(function () {
      console.log(isEditable(deepActiveElement())
        ? "__kestrel:mode:insert" : "__kestrel:mode:normal");
    }, 30);
  }, true);

  // ---- Scrolling -----------------------------------------------------------
  function isScrollable(el) {
    if (!el || el === document.body) return false;
    const style = getComputedStyle(el);
    const oy = style.overflowY, ox = style.overflowX;
    const canY = (oy === "auto" || oy === "scroll" || oy === "overlay") &&
      el.scrollHeight > el.clientHeight + 2;
    const canX = (ox === "auto" || ox === "scroll" || ox === "overlay") &&
      el.scrollWidth > el.clientWidth + 2;
    return canY || canX;
  }

  let lastScrollTarget = null;

  function scrollTarget() {
    const root = document.scrollingElement || document.documentElement;
    if (root.scrollHeight > window.innerHeight + 2) return root;
    if (lastScrollTarget && document.contains(lastScrollTarget) &&
        isScrollable(lastScrollTarget)) return lastScrollTarget;
    // Page itself doesn't scroll (common in web apps): pick the largest
    // visible scrollable element.
    let best = null, bestArea = 0;
    const all = document.querySelectorAll("*");
    for (let i = 0; i < all.length && i < 5000; i++) {
      const el = all[i];
      if (el.scrollHeight <= el.clientHeight + 2) continue;
      if (!isScrollable(el)) continue;
      const r = el.getBoundingClientRect();
      const area = Math.max(0, Math.min(r.right, innerWidth) - Math.max(r.left, 0)) *
        Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, 0));
      if (area > bestArea) { best = el; bestArea = area; }
    }
    lastScrollTarget = best;
    return best || root;
  }

  function scrollBy(dx, dy) {
    const t = scrollTarget();
    t.scrollBy({ left: dx, top: dy, behavior: "instant" });
  }

  function scrollPage(fraction) {
    const t = scrollTarget();
    const h = t === (document.scrollingElement || document.documentElement)
      ? window.innerHeight : t.clientHeight;
    t.scrollBy({ top: h * fraction, behavior: "instant" });
  }

  function scrollTo(where) {
    const t = scrollTarget();
    t.scrollTo({ top: where === "top" ? 0 : t.scrollHeight, behavior: "instant" });
  }

  function scrollPercent() {
    const t = scrollTarget();
    const max = t.scrollHeight - t.clientHeight;
    if (max <= 0) return -1;
    return Math.round((t.scrollTop / max) * 100);
  }

  // ---- Focus helpers -------------------------------------------------------
  function blur() {
    const el = deepActiveElement();
    if (el && el !== document.body && el.blur) el.blur();
    window.getSelection && window.getSelection().removeAllRanges();
  }

  function rendered(el) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const s = getComputedStyle(el);
    return s.visibility !== "hidden" && s.display !== "none" && parseFloat(s.opacity) > 0.05;
  }

  function inViewport(el) {
    const r = el.getBoundingClientRect();
    return !(r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth);
  }

  function visible(el) {
    return inViewport(el) && rendered(el);
  }

  function focusInput() {
    const inputs = Array.from(document.querySelectorAll(
      "input, textarea, [contenteditable=''], [contenteditable=true]"))
      .filter(function (el) { return isEditable(el) && rendered(el); });
    if (!inputs.length) return false;
    // Prefer an input that's already on screen, otherwise the first one.
    const el = inputs.find(inViewport) || inputs[0];
    el.scrollIntoView({ block: "center", behavior: "instant" });
    el.focus();
    if (el.select) try { el.select(); } catch (e) { /* ignore */ }
    return true;
  }

  // ---- Link hints ----------------------------------------------------------
  const CLICKABLE = [
    "a[href]", "area[href]", "button", "input:not([type=hidden])", "textarea",
    "select", "summary", "label[for]", "details",
    "[role=button]", "[role=link]", "[role=tab]", "[role=checkbox]",
    "[role=menuitem]", "[role=option]", "[role=switch]", "[role=radio]",
    "[onclick]", "[contenteditable='']", "[contenteditable=true]",
    "[tabindex]:not([tabindex='-1'])", "[jsaction]",
  ].join(",");

  let hintState = null;

  function hintStrings(count, chars) {
    // Prefix-free labels, shortest first (same scheme as Vimium).
    let hints = [""], offset = 0;
    while (hints.length - offset < count || hints.length === 1) {
      const h = hints[offset++];
      for (const c of chars) hints.push(c + h);
    }
    return hints.slice(offset, offset + count).sort()
      .map(function (h) { return h.split("").reverse().join(""); });
  }

  function collectTargets(mode) {
    const seen = new Set();
    const out = [];
    const nodes = document.querySelectorAll(mode === "input"
      ? "input:not([type=hidden]), textarea, [contenteditable=''], [contenteditable=true]"
      : CLICKABLE);
    for (const el of nodes) {
      if (seen.has(el)) continue;
      if (el.disabled) continue;
      if (!visible(el)) continue;
      // Skip elements hidden behind something else.
      const r = el.getBoundingClientRect();
      const cx = Math.min(Math.max(r.left + Math.min(r.width / 2, 12), 0), innerWidth - 1);
      const cy = Math.min(Math.max(r.top + r.height / 2, 0), innerHeight - 1);
      const hit = document.elementFromPoint(cx, cy);
      if (hit && hit !== el && !el.contains(hit) && !hit.contains(el)) {
        const hitLink = hit.closest && hit.closest(CLICKABLE);
        if (hitLink !== el) continue;
      }
      // Don't hint a wrapper whose only job is to contain another target.
      if (el.tagName !== "A" && el.querySelector("a[href],button") &&
          el.getAttribute("role") === null && !el.onclick) {
        // Keep it only if it is small (likely an icon button).
        if (r.width * r.height > 40000) continue;
      }
      seen.add(el);
      out.push({ el: el, rect: r });
    }
    return out;
  }

  function clearHints() {
    if (hintState && hintState.root) hintState.root.remove();
    hintState = null;
  }

  function showHints(opts) {
    clearHints();
    const targets = collectTargets(opts.target || "all");
    if (!targets.length) return 0;
    const labels = hintStrings(targets.length, opts.chars || "asdfghjkl");
    const root = document.createElement("div");
    root.setAttribute("data-kestrel-hints", "");
    root.style.setProperty("all", "initial", "important");
    root.style.setProperty("position", "fixed", "important");
    root.style.setProperty("inset", "0", "important");
    root.style.setProperty("pointer-events", "none", "important");
    root.style.setProperty("z-index", "2147483647", "important");
    const items = [];
    targets.forEach(function (t, i) {
      const span = document.createElement("span");
      const s = span.style;
      s.setProperty("all", "initial", "important");
      s.setProperty("position", "fixed", "important");
      s.setProperty("left", Math.max(0, t.rect.left - 4) + "px", "important");
      s.setProperty("top", Math.max(0, t.rect.top - 4) + "px", "important");
      s.setProperty("background", opts.bg, "important");
      s.setProperty("color", opts.fg, "important");
      s.setProperty("border", "1px solid " + opts.border, "important");
      s.setProperty("border-radius", "3px", "important");
      s.setProperty("padding", "1px 4px", "important");
      s.setProperty("font", "bold 12px/1.3 'JetBrainsMono Nerd Font', 'JetBrains Mono', monospace", "important");
      s.setProperty("text-transform", "uppercase", "important");
      s.setProperty("box-shadow", "0 2px 6px rgba(0,0,0,.35)", "important");
      span.textContent = labels[i];
      root.appendChild(span);
      items.push({ label: labels[i], el: t.el, span: span });
    });
    (document.body || document.documentElement).appendChild(root);
    hintState = { root: root, items: items, typed: "", opts: opts };
    return items.length;
  }

  function activate(el, newTab) {
    const link = el.closest ? el.closest("a[href]") : null;
    if (newTab && link) return { href: link.href };
    if (isEditable(el)) {
      el.focus();
      if (el.select && el.tagName !== "SELECT") try { el.select(); } catch (e) { /* ignore */ }
      return { editable: true };
    }
    const r = el.getBoundingClientRect();
    const init = {
      bubbles: true, cancelable: true, view: window,
      clientX: r.left + r.width / 2, clientY: r.top + r.height / 2, button: 0,
    };
    for (const type of ["pointerover", "mouseover", "pointerdown", "mousedown"]) {
      el.dispatchEvent(new (type.startsWith("pointer") ? PointerEvent : MouseEvent)(type, init));
    }
    if (el.focus) el.focus({ preventScroll: true });
    for (const type of ["pointerup", "mouseup"]) {
      el.dispatchEvent(new (type.startsWith("pointer") ? PointerEvent : MouseEvent)(type, init));
    }
    el.click();
    return { clicked: true };
  }

  function hintKey(key) {
    if (!hintState) return { status: "none" };
    if (key === "<BS>") hintState.typed = hintState.typed.slice(0, -1);
    else hintState.typed += key.toLowerCase();
    const typed = hintState.typed;
    let matches = 0, match = null;
    for (const it of hintState.items) {
      if (it.label.startsWith(typed)) {
        matches++;
        match = it;
        it.span.style.setProperty("display", "inline", "important");
        it.span.style.setProperty("opacity", typed ? "1" : "1", "important");
        it.span.innerHTML = "";
        const done = document.createElement("span");
        done.style.setProperty("all", "initial", "important");
        done.style.setProperty("font", "inherit", "important");
        done.style.setProperty("color", hintState.opts.dim, "important");
        done.textContent = it.label.slice(0, typed.length);
        it.span.appendChild(done);
        it.span.appendChild(document.createTextNode(it.label.slice(typed.length)));
      } else {
        it.span.style.setProperty("display", "none", "important");
      }
    }
    if (matches === 0) { clearHints(); return { status: "none" }; }
    if (matches === 1 && match.label === typed) {
      const action = hintState.opts.action;
      clearHints();
      const link = match.el.closest ? match.el.closest("a[href]") : null;
      if (action === "yank") return { status: "done", yank: link ? link.href : (match.el.value || match.el.textContent || "").trim() };
      const res = activate(match.el, action === "tab");
      res.status = "done";
      return res;
    }
    return { status: "pending" };
  }

  window.__kestrel = {
    isEditable: function () { return isEditable(deepActiveElement()); },
    blur: blur,
    focusInput: focusInput,
    scrollBy: scrollBy,
    scrollPage: scrollPage,
    scrollTo: scrollTo,
    scrollPercent: scrollPercent,
    showHints: showHints,
    hintKey: hintKey,
    clearHints: clearHints,
  };
})();
