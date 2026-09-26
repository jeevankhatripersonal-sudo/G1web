#!/usr/bin/env python3
"""
optimize_embeds.py - make the Spotify and BeatStars embeds load smoothly

Put this file next to index.html and run:

    python optimize_embeds.py            (Windows)
    python3 optimize_embeds.py           (Mac / Linux)

Options:
    --dry-run      show what would change, save nothing
    --folder PATH  run on a different folder

What it does:
  1. Backs up index.html to index.before-embeds.html.
  2. Replaces each Spotify / BeatStars <iframe> with a placeholder box of the
     same height (with a soft shimmer in your site's colours).
  3. Adds a script that creates the real iframe only after the page has
     finished loading and the visitor is getting near it, then fades it in.
     Tapping the placeholder loads it instantly.
  4. Adds a <noscript> fallback so the embeds still work with JS disabled.

Safe to run more than once: it skips anything already converted.
"""

import argparse
import html as htmllib
import re
import shutil
import sys
from pathlib import Path

CSS_MARKER = "/* -- Smooth lazy embeds (added by optimize_embeds.py) -- */"
JS_MARKER = "// -- Smooth lazy embeds (added by optimize_embeds.py) --"

CSS = CSS_MARKER + """
.embed { position:relative; width:100%; border-radius:4px; overflow:hidden; background:var(--ash); cursor:pointer; }
.embed::before {
  content:''; position:absolute; inset:0;
  background:linear-gradient(90deg, transparent, rgba(255,255,255,0.05), transparent);
  transform:translateX(-100%); animation:embedShimmer 1.6s ease-in-out infinite;
}
.embed.is-loaded { cursor:default; }
.embed.is-loaded::before { display:none; }
.embed iframe { position:absolute; inset:0; width:100%; height:100%; border:0; opacity:0; transition:opacity .5s ease; }
.embed.is-loaded iframe { opacity:1; }
@keyframes embedShimmer { to { transform:translateX(100%); } }
@media (prefers-reduced-motion: reduce) { .embed::before { animation:none; } .embed iframe { transition:none; } }
"""

JS = JS_MARKER + r"""
(function () {
  const embeds = document.querySelectorAll('.embed[data-src]');
  if (!embeds.length) return;

  function loadEmbed(el) {
    if (el.dataset.loaded) return;
    el.dataset.loaded = '1';
    const f = document.createElement('iframe');
    f.src = el.dataset.src;
    f.title = el.dataset.title || '';
    if (el.dataset.allow) f.allow = el.dataset.allow;
    f.setAttribute('allowfullscreen', '');
    f.onload = () => el.classList.add('is-loaded');
    setTimeout(() => el.classList.add('is-loaded'), 8000); // never leave it hidden
    el.appendChild(f);
  }

  embeds.forEach(el => el.addEventListener('click', () => loadEmbed(el), { once: true }));

  function start() {
    if (!('IntersectionObserver' in window)) { embeds.forEach(loadEmbed); return; }
    const io = new IntersectionObserver((entries, obs) => {
      entries.forEach(e => { if (e.isIntersecting) { loadEmbed(e.target); obs.unobserve(e.target); } });
    }, { rootMargin: '600px 0px' });
    embeds.forEach(el => io.observe(el));
  }

  const kick = () => ('requestIdleCallback' in window)
    ? requestIdleCallback(start, { timeout: 2000 })
    : setTimeout(start, 1200);
  if (document.readyState === 'complete') kick();
  else window.addEventListener('load', kick);
})();
"""

TARGETS = [
    # (name, url pattern, default height, default title)
    ("Spotify", r"open\.spotify\.com/embed", 576, "Spotify playlist"),
    ("BeatStars", r"player\.beatstars\.com", 880, "BeatStars beat store"),
]


def attr(tag, name):
    m = re.search(rf'\b{name}\s*=\s*"([^"]*)"', tag, flags=re.I)
    return m.group(1) if m else None


def convert_iframes(page):
    report = []

    def repl(m):
        whole = m.group(0)
        open_tag = m.group(1)
        src = attr(open_tag, "src") or ""
        for name, pattern, default_h, default_title in TARGETS:
            if re.search(pattern, src):
                h = attr(open_tag, "height") or str(default_h)
                h = h if h.endswith("px") or h.endswith("%") else h + "px"
                title = attr(open_tag, "title") or default_title
                allow = attr(open_tag, "allow")
                parts = [
                    f'<div class="embed" style="height:{h}"',
                    f'data-title="{htmllib.escape(title, quote=True)}"',
                    f'data-src="{src}"',
                ]
                if allow:
                    parts.append(f'data-allow="{allow}"')
                div = "\n  ".join(parts) + f"><noscript>{whole}</noscript></div>"
                report.append(f"{name}: iframe -> smooth lazy embed (height {h})")
                return div
        return whole

    # Skip iframes that are already inside <noscript> (already converted).
    chunks = re.split(r"(<noscript>.*?</noscript>)", page, flags=re.S | re.I)
    for i, chunk in enumerate(chunks):
        if chunk.lower().startswith("<noscript>"):
            continue
        chunks[i] = re.sub(r"(<iframe\b[^>]*>)\s*</iframe>", repl, chunk, flags=re.I | re.S)
    return "".join(chunks), report


def insert_before_last(page, closing_tag, block):
    idx = page.lower().rfind(closing_tag)
    if idx == -1:
        return page, False
    return page[:idx] + "\n" + block + page[idx:], True


def main():
    ap = argparse.ArgumentParser(description="Make Spotify/BeatStars embeds load smoothly.")
    ap.add_argument("--folder", default=".")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    path = Path(args.folder).resolve() / "index.html"
    if not path.exists():
        print(f"index.html not found in {path.parent}")
        sys.exit(1)

    original = path.read_text(encoding="utf-8")
    page, report = convert_iframes(original)

    if CSS_MARKER not in page:
        page, ok = insert_before_last(page, "</style>", CSS)
        report.append("CSS for placeholders added" if ok else "! no </style> found, CSS not added")
    else:
        report.append("CSS already present")

    if JS_MARKER not in page:
        page, ok = insert_before_last(page, "</script>", JS)
        report.append("loader script added" if ok else "! no </script> found, script not added")
    else:
        report.append("loader script already present")

    print("index.html:")
    for line in report:
        print("  " + line)

    if page == original:
        print("\nNothing to change - already done.")
        return
    if args.dry_run:
        print("\n(dry run) nothing saved.")
        return

    backup = path.with_name("index.before-embeds.html")
    shutil.copy2(path, backup)
    path.write_text(page, encoding="utf-8")
    print(f"\nSaved. Previous version kept as {backup.name}")
    print("Open the page and scroll down: the boxes shimmer briefly, then the players fade in.")


if __name__ == "__main__":
    main()
