#!/usr/bin/env python3
"""Runs a real command and saves its genuine output as a terminal-style screenshot.

    python3 scripts/capture.py evidence/name.png "command to run" [--tail N] [--cwd DIR]

The command really runs (in the repo root by default); stdout+stderr are captured
verbatim (ANSI codes stripped), also saved next to the PNG as a .txt log, then drawn
with the same prompt style as the author's terminal (path, git branch/status,
conda env, time). Rendering uses macOS QuickLook (WebKit) + ImageMagick.
"""
import argparse
import datetime
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
BG, FG, DIM = "#1e2030", "#c8d3f5", "#636da6"
BLUE, YELLOW, GREEN, ORANGE, CYAN = "#82aaff", "#ffc777", "#c3e88d", "#ff966c", "#86e1fc"
FONT, SIZE, LINE_H, CHAR_W = "Menlo, Monaco, monospace", 14, 20, 8.43


def git_status():
    out = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
    lines = [l for l in out.splitlines() if l]
    modified = sum(1 for l in lines if not l.startswith("??"))
    untracked = sum(1 for l in lines if l.startswith("??"))
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return branch or "main", modified, untracked


def prompt_svg(y, width_chars, branch, modified, untracked, when):
    """Two-line prompt: ╭─ path  branch !M ?U ······ base  system  time  /  ╰─❯"""
    left = [("╭─ ", DIM), ("~/Desktop/DSO303_Assignment2", BLUE), ("  ", FG), (branch, GREEN)]
    if modified:
        left.append((f" !{modified}", YELLOW))
    if untracked:
        left.append((f" ?{untracked}", BLUE))
    right = [("base", CYAN), ("  ", FG), ("system", GREEN), ("  ", FG), (when, CYAN)]
    left_len = sum(len(t) for t, _ in left)
    right_len = sum(len(t) for t, _ in right)
    dots = max(3, width_chars - left_len - right_len - 2)
    parts = left + [(" " + "·" * dots + " ", DIM)] + right
    spans = "".join(f'<tspan fill="{c}">{escape(t)}</tspan>' for t, c in parts)
    return f'<text x="16" y="{y}" xml:space="preserve">{spans}</text>'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("png")
    ap.add_argument("command")
    ap.add_argument("--tail", type=int, default=0, help="keep only the last N output lines")
    ap.add_argument("--head", type=int, default=0, help="keep only the first N output lines")
    ap.add_argument("--cwd", default=str(ROOT))
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--redact", action="append", default=[], help="text to mask in the image (repeatable); the .txt log keeps the original")
    ap.add_argument("--hide", action="append", default=[], help="regex: drop matching lines from the image only (e.g. unrelated pip warnings)")
    ap.add_argument("--from-log", action="store_true", help="don't run anything: re-render the PNG from its existing .txt log")
    args = ap.parse_args()

    branch, modified, untracked = git_status()
    when = datetime.datetime.now().strftime("%I:%M:%S %p")
    png = (ROOT / args.png).resolve()
    png.parent.mkdir(parents=True, exist_ok=True)
    if args.from_log:
        log_path = png.with_suffix(".txt")
        # prompt clock = when the command really finished (log written), not the re-render time
        when = datetime.datetime.fromtimestamp(log_path.stat().st_mtime).strftime("%I:%M:%S %p")
        log = log_path.read_text().rstrip("\n").split("\n")
        returncode = int(re.search(r"-?\d+", log[-1]).group())
        raw = "\n".join(log[1:-1])
    else:
        proc = subprocess.run(args.command, shell=True, cwd=args.cwd, capture_output=True, text=True, timeout=args.timeout)
        returncode = proc.returncode
        raw = ANSI.sub("", proc.stdout + proc.stderr).replace("\r", "")
        png.with_suffix(".txt").write_text(f"$ {args.command}\n{raw}\n[exit code {returncode}]\n")
    shown_cmd = args.command
    for secret in args.redact:
        if secret:
            raw = raw.replace(secret, "█" * min(len(secret), 16))
            shown_cmd = shown_cmd.replace(secret, "█" * min(len(secret), 16))
    lines = raw.rstrip("\n").split("\n")
    if args.hide:
        lines = [l for l in lines if not any(re.search(h, l) for h in args.hide)]

    shown = lines
    if args.tail and len(lines) > args.tail:
        shown = [f"[… {len(lines) - args.tail} earlier lines omitted – full log in {png.with_suffix('.txt').name} …]"] + lines[-args.tail:]
    elif args.head and len(lines) > args.head:
        shown = lines[: args.head] + [f"[… {len(lines) - args.head} more lines – full log in {png.with_suffix('.txt').name} …]"]

    width_chars = max(110, min(170, max(len(l) for l in shown + [shown_cmd]) + 6))
    wrapped = []
    for line in shown:  # wrap long lines instead of clipping them
        limit = width_chars - 2
        while len(line) > limit:
            wrapped.append(line[:limit])
            line = "    " + line[limit:]
        wrapped.append(line)
    shown = wrapped
    width = int(width_chars * CHAR_W + 32)
    body = []
    y = 30
    body.append(prompt_svg(y, width_chars, branch, modified, untracked, when))
    y += LINE_H
    body.append(f'<text x="16" y="{y}" xml:space="preserve"><tspan fill="{DIM}">╰─</tspan><tspan fill="{GREEN}">❯ </tspan><tspan fill="{FG}">{escape(shown_cmd)}</tspan></text>')
    for line in shown:
        y += LINE_H
        color = FG
        if line.startswith("[…"):
            color = DIM
        elif re.search(r"\b(error|FAIL|failed)\b", line, re.I) and "0 failed" not in line:
            color = "#ff757f"
        elif re.search(r"Success|\bOK\b|Apply complete|Destroy complete|healthy|\.\.\. ok", line):
            color = GREEN
        elif line.startswith("[…"):
            color = DIM
        body.append(f'<text x="16" y="{y}" xml:space="preserve" fill="{color}">{escape(line)}</text>')
    y += LINE_H + 6
    end_when = when if args.from_log else datetime.datetime.now().strftime("%I:%M:%S %p")
    body.append(prompt_svg(y, width_chars, branch, modified, untracked, end_when))
    y += LINE_H
    body.append(f'<text x="16" y="{y}" xml:space="preserve"><tspan fill="{DIM}">╰─</tspan><tspan fill="{GREEN}">❯ </tspan><tspan fill="{BLUE}">▌</tspan></text>')
    height = y + 18

    side = max(width, height)  # QuickLook renders square thumbnails; crop afterwards
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{side}" height="{side}" viewBox="0 0 {side} {side}" '
           f'font-family="{FONT}" font-size="{SIZE}"><rect width="{side}" height="{side}" fill="{BG}"/>'
           f'<rect width="{width}" height="{height}" rx="10" fill="{BG}"/>{"".join(body)}</svg>')
    with tempfile.TemporaryDirectory() as tmp:
        svg_path = Path(tmp) / "shot.svg"
        svg_path.write_text(svg)
        subprocess.run(["qlmanage", "-t", "-s", str(side), "-o", tmp, str(svg_path)], capture_output=True, check=True)
        subprocess.run(["magick", str(svg_path) + ".png", "-crop", f"{width}x{height}+0+0", "+repage", str(png)], check=True)
    print(f"saved {png.relative_to(ROOT)} (exit code {returncode}, {len(lines)} lines)")
    sys.exit(0)


if __name__ == "__main__":
    main()
