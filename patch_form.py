#!/usr/bin/env python3
"""
patch_form.py - switch the contact form from Google Sheets to /api/contact

Put this next to index.html and run:
    python patch_form.py        (Windows)
    python3 patch_form.py       (Mac / Linux)

It backs up index.html to index.before-form.html, removes the Google Sheets
URL, adds a hidden anti-spam field, and replaces the submit code with one that
sends to your own Vercel function and shows a real error if saving fails.
Safe to run more than once.
"""

import re
import shutil
import sys
from pathlib import Path

HONEYPOT = ('\n        <input type="text" id="f-website" name="website" tabindex="-1" '
            'autocomplete="off" aria-hidden="true" '
            'style="position:absolute;left:-9999px;width:1px;height:1px;opacity:0;">')

NEW_HANDLER = r"""document.getElementById('f-submit').addEventListener('click', async function() {
    const name    = document.getElementById('f-name').value.trim();
    const email   = document.getElementById('f-email').value.trim();
    const service = document.getElementById('f-service').value;
    const message = document.getElementById('f-message').value.trim();
    const hp      = document.getElementById('f-website');
    const website = hp ? hp.value : '';

    if (!name || !email || !service) {
      alert('Please fill in your name, email, and select a service.');
      return;
    }

    const btn = document.getElementById('f-submit');
    const ok  = document.getElementById('f-success');
    const bad = document.getElementById('f-error');
    btn.textContent = 'Sending...';
    btn.disabled = true;
    btn.style.opacity = '0.6';
    ok.style.display = 'none';
    bad.style.display = 'none';

    try {
      const res = await fetch('/api/contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, service, message, website })
      });
      if (!res.ok) throw new Error('Server responded ' + res.status);

      ok.style.display = 'block';
      ['f-name', 'f-email', 'f-service', 'f-message'].forEach(id => { document.getElementById(id).value = ''; });
    } catch (err) {
      console.error(err);
      bad.style.display = 'block';
    } finally {
      btn.textContent = 'Send Inquiry';
      btn.disabled = false;
      btn.style.opacity = '1';
    }
  });"""


def find_call_end(s, start):
    """From the '(' at `start`, return index just past the matching ')' + ';'."""
    depth, i, quote = 0, start, None
    while i < len(s):
        c = s[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif s.startswith("//", i):
            nl = s.find("\n", i)
            i = len(s) if nl == -1 else nl
            continue
        elif s.startswith("/*", i):
            close = s.find("*/", i + 2)
            i = len(s) if close == -1 else close + 2
            continue
        elif c in "'\"`":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                j = i + 1
                if j < len(s) and s[j] == ";":
                    j += 1
                return j
        i += 1
    return -1


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve() / "index.html"
    if not path.exists():
        print(f"index.html not found in {path.parent}")
        sys.exit(1)
    page = path.read_text(encoding="utf-8")
    original = page

    if "fetch('/api/contact'" in page:
        print("Form already points to /api/contact - nothing to do.")
        return

    # 1. Replace the submit handler
    marker = "document.getElementById('f-submit').addEventListener("
    start = page.find(marker)
    if start == -1:
        print("Could not find the f-submit handler; no changes made.")
        sys.exit(1)
    end = find_call_end(page, start + len(marker) - 1)
    if end == -1:
        print("Could not parse the f-submit handler; no changes made.")
        sys.exit(1)
    page = page[:start] + NEW_HANDLER + page[end:]
    print("  submit code now sends to /api/contact")

    # 2. Remove the Google Sheets URL (and its comment line)
    page, n = re.subn(r"[ \t]*//[^\n]*Google Sheets[^\n]*\n", "", page)
    page, m = re.subn(r"[ \t]*const SHEET_URL\s*=\s*'[^']*';[ \t]*\n?", "", page)
    if m:
        print("  Google Sheets URL removed")

    # 3. Hidden honeypot field right after the message textarea
    if 'id="f-website"' not in page:
        page, k = re.subn(r'(<textarea[^>]*id="f-message"[^>]*>.*?</textarea>)',
                          lambda mt: mt.group(1) + HONEYPOT, page, count=1, flags=re.S)
        print("  anti-spam field added" if k else "  ! message box not found; anti-spam field skipped")

    backup = path.with_name("index.before-form.html")
    shutil.copy2(path, backup)
    path.write_text(page, encoding="utf-8")
    print(f"\nSaved index.html (previous version in {backup.name})")


if __name__ == "__main__":
    main()
