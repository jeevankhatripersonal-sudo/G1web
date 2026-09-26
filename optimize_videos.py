#!/usr/bin/env python3
"""
optimize_videos.py - compress site videos, make lazy posters, update index.html

Put this file in the same folder as index.html and your .mp4 files, then run:

    python optimize_videos.py            (Windows)
    python3 optimize_videos.py           (Mac / Linux)

Options:
    --dry-run      show what would happen, change nothing
    --no-html      only process videos, leave index.html alone
    --folder PATH  run on a different folder

What it does:
  1. Backs up every original video to ./original_videos/ (once; later runs
     always re-encode from these originals, so you can run it again safely).
  2. Silent autoplay previews (class "lazy-autoplay-video" or "preview" in the
     name): removes audio, max 720p, CRF 28, fast-start.
     Before & After clips (class "lazy-video" or ba1.mp4 etc.): keeps audio
     (AAC 160k), max 720p, CRF 24, fast-start.
     A new file only replaces the old one if it is actually smaller.
  3. Makes a small poster image (NAME.webp, 640px wide) for each video.
  4. Backs up index.html to index.backup.html, adds data-poster="..." to each
     <video>, and adds a small script that loads posters only when the video
     is near the screen.

Requires ffmpeg (includes ffprobe):
    Windows:  winget install ffmpeg      (then open a NEW terminal)
    Mac:      brew install ffmpeg
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ---- Settings you can tweak ------------------------------------------------
MAX_HEIGHT = 720          # videos taller than this are scaled down (never up)
PREVIEW_CRF = 28          # silent previews: higher = smaller file, lower quality
BA_CRF = 24               # before/after clips: keep a bit more quality
BA_AUDIO_BITRATE = "160k"
POSTER_WIDTH = 640
POSTER_QUALITY = 75       # webp quality 0-100
# -----------------------------------------------------------------------------

BACKUP_DIR = "original_videos"
POSTER_MARKER = "// -- Lazy video posters (added by optimize_videos.py) --"

POSTER_JS = POSTER_MARKER + r"""
(function () {
  const vids = document.querySelectorAll('video[data-poster]');
  const setPoster = v => { if (!v.poster) v.poster = v.dataset.poster; };
  if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver((entries, obs) => {
      entries.forEach(e => { if (e.isIntersecting) { setPoster(e.target); obs.unobserve(e.target); } });
    }, { rootMargin: '600px 0px' });
    vids.forEach(v => io.observe(v));
  } else {
    vids.forEach(setPoster);
  }
})();
"""


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024


def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def check_ffmpeg():
    missing = [t for t in ("ffmpeg", "ffprobe") if shutil.which(t) is None]
    if missing:
        print("ERROR: could not find " + " and ".join(missing) + ".")
        print("Install it first:")
        print("  Windows:  winget install ffmpeg   (then open a NEW terminal)")
        print("  Mac:      brew install ffmpeg")
        sys.exit(1)


def duration_of(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)])
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def classify_from_html(html):
    """Map video filename -> 'preview' or 'ba' using the classes in index.html."""
    kinds = {}
    for tag in re.findall(r"<video\b[^>]*>", html, flags=re.I):
        src = re.search(r'data-src="([^"]+)"', tag)
        if not src:
            continue
        name = Path(src.group(1)).name
        if "lazy-autoplay-video" in tag or " muted" in tag:
            kinds[name] = "preview"
        elif "lazy-video" in tag:
            kinds[name] = "ba"
    return kinds


def guess_kind(name, html_kinds):
    if name in html_kinds:
        return html_kinds[name]
    low = name.lower()
    if re.match(r"ba\d+", low):
        return "ba"
    if "preview" in low:
        return "preview"
    return "ba"  # unknown: keep audio to be safe


def encode(src, dst, kind):
    scale = f"scale=-2:'min({MAX_HEIGHT},ih)'"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-stats",
           "-i", str(src), "-vf", scale,
           "-c:v", "libx264", "-preset", "slow",
           "-crf", str(PREVIEW_CRF if kind == "preview" else BA_CRF),
           "-pix_fmt", "yuv420p", "-map_metadata", "-1",
           "-movflags", "+faststart"]
    if kind == "preview":
        cmd += ["-an"]
    else:
        cmd += ["-c:a", "aac", "-b:a", BA_AUDIO_BITRATE]
    cmd.append(str(dst))
    return subprocess.run(cmd).returncode == 0


def make_poster(src, dst):
    t = min(1.0, duration_of(src) / 2) if duration_of(src) > 0 else 0
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1",
           "-vf", f"scale={POSTER_WIDTH}:-2",
           "-c:v", "libwebp", "-quality", str(POSTER_QUALITY), str(dst)]
    return run(cmd).returncode == 0 and dst.exists()


def update_html(html_path, posters, dry_run):
    html = html_path.read_text(encoding="utf-8")
    changed = 0

    def add_poster(m):
        nonlocal changed
        tag = m.group(0)
        if "data-poster=" in tag:
            return tag
        src = re.search(r'data-src="([^"]+)"', tag)
        if not src:
            return tag
        stem = Path(src.group(1)).stem
        if stem not in posters:
            return tag
        poster_path = str(Path(src.group(1)).with_suffix(".webp")).replace("\\", "/")
        changed += 1
        return tag.replace(src.group(0), f'{src.group(0)} data-poster="{poster_path}"', 1)

    new_html = re.sub(r"<video\b[^>]*>", add_poster, html, flags=re.I)

    added_js = False
    if POSTER_MARKER not in new_html:
        idx = new_html.rfind("</script>")
        if idx != -1:
            new_html = new_html[:idx] + "\n" + POSTER_JS + new_html[idx:]
            added_js = True
        else:
            print("  ! No <script> block found; poster script not added.")

    print(f"  {changed} <video> tags got a data-poster attribute")
    print("  poster loading script " + ("added" if added_js else "already present"))

    if dry_run or (changed == 0 and not added_js):
        return
    backup = html_path.with_name("index.backup.html")
    shutil.copy2(html_path, backup)
    html_path.write_text(new_html, encoding="utf-8")
    print(f"  saved index.html (previous version in {backup.name})")


def main():
    ap = argparse.ArgumentParser(description="Optimise website videos.")
    ap.add_argument("--folder", default=".", help="folder with index.html and videos")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-html", action="store_true")
    args = ap.parse_args()

    check_ffmpeg()
    folder = Path(args.folder).resolve()
    html_path = folder / "index.html"
    html = html_path.read_text(encoding="utf-8") if html_path.exists() else ""
    html_kinds = classify_from_html(html)

    videos = sorted(p for p in folder.glob("*.mp4") if not p.name.startswith("_tmp_"))
    if not videos:
        print(f"No .mp4 files found in {folder}")
        sys.exit(0)

    backup_dir = folder / BACKUP_DIR
    print(f"Folder: {folder}")
    print(f"Found {len(videos)} videos\n")

    results, posters = [], set()
    for i, vid in enumerate(videos, 1):
        kind = guess_kind(vid.name, html_kinds)
        label = "silent preview" if kind == "preview" else "before/after (audio kept)"
        print(f"[{i}/{len(videos)}] {vid.name}  ->  {label}")

        original = backup_dir / vid.name
        if args.dry_run:
            print("  (dry run) would back up, encode and make poster\n")
            continue

        backup_dir.mkdir(exist_ok=True)
        if not original.exists():
            shutil.copy2(vid, original)
        before = original.stat().st_size

        tmp = folder / f"_tmp_{vid.name}"
        if encode(original, tmp, kind) and tmp.exists():
            after = tmp.stat().st_size
            if after < before:
                tmp.replace(vid)
                print(f"  {human(before)} -> {human(after)}  (-{100 - after * 100 // before}%)")
            else:
                tmp.unlink()
                shutil.copy2(original, vid)
                after = before
                print("  new file was not smaller; kept original")
        else:
            if tmp.exists():
                tmp.unlink()
            after = before
            print("  ! encoding failed; original left in place")
        results.append((vid.name, before, after))

        poster = vid.with_suffix(".webp")
        if make_poster(original, poster):
            posters.add(vid.stem)
            print(f"  poster: {poster.name} ({human(poster.stat().st_size)})")
        else:
            print("  ! could not create poster")
        print()

    if results:
        tb = sum(r[1] for r in results)
        ta = sum(r[2] for r in results)
        print("=" * 60)
        print(f"{'File':40} {'Before':>9} {'After':>9}")
        for name, b, a in results:
            print(f"{name[:40]:40} {human(b):>9} {human(a):>9}")
        print("-" * 60)
        saved = 100 - ta * 100 // tb if tb else 0
        print(f"{'TOTAL':40} {human(tb):>9} {human(ta):>9}   saved {saved}%")
        print("=" * 60)
        print(f"Originals are safe in ./{BACKUP_DIR}/\n")

    if args.dry_run:
        posters = {v.stem for v in videos}
    if not args.no_html and html_path.exists():
        print("Updating index.html:")
        update_html(html_path, posters, args.dry_run)
    elif not html_path.exists():
        print("index.html not found here; skipped HTML update.")

    print("\nDone. Open the site, check a few clips look and sound right, then upload:")
    print("  the new .mp4 files, the new .webp posters, and index.html")


if __name__ == "__main__":
    main()
