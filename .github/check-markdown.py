#!/usr/bin/env python3
"""Two render-breaking defects in this repo's markdown, both of which have shipped before.

Neither is visible in a diff and neither shows up in prose review: a dropped code-fence closer turns
the next ~90 lines of guidance into one grey block, and a raw `|` inside a table cell silently
truncates the rest of that row from the rendered output. The second one cost the `domain records`
row its 403-agent-credentials warning; the first one has now landed twice at the same spot in
migrate/insforge.md.

Both are mechanical, so they belong here rather than in a third human review.
"""
import pathlib
import re
import sys

FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})(.*)$")
problems = []

for path in sorted(pathlib.Path(".").rglob("*.md")):
    if ".git" in path.parts:
        continue
    lines = path.read_text(encoding="utf-8").split("\n")

    # 1. Fence pairing. A CLOSER must carry nothing after its run of backticks — ``` followed by
    #    prose opens a new block instead of closing one, which is exactly how the insforge.md
    #    regression reads.
    open_at = None
    marker = ""
    marker_len = 0
    for n, line in enumerate(lines, 1):
        m = FENCE.match(line)
        if not m:
            continue
        run, tail = m.group(1), m.group(2).strip()
        if open_at is None:
            open_at, marker, marker_len = n, run[0], len(run)
        elif run[0] == marker and len(run) >= marker_len:
            if tail:
                problems.append(
                    f"{path}:{n}: code fence closer has trailing text {tail[:40]!r} — "
                    f"a closer must be bare, so the block opened at line {open_at} never closes"
                )
            open_at = None
    if open_at is not None:
        problems.append(f"{path}:{open_at}: code fence opened here is never closed")

    # 2. Table rows must agree on their column count. A raw `|` inside backticks is still a
    #    delimiter in GFM, so a row with extra cells loses everything past the header's width.
    #    Only contiguous runs that have a delimiter row are treated as tables.
    inside_fence, fence_marker = False, ""
    n = 0
    while n < len(lines):
        line = lines[n]
        m = FENCE.match(line)
        if m:
            run = m.group(1)[0]
            if not inside_fence:
                inside_fence, fence_marker = True, run
            elif run == fence_marker:
                inside_fence = False
            n += 1
            continue
        # GFM does not require the outer pipes, and the pipe-less form carries the very defect this
        # checks for, so a run is a table candidate when it merely CONTAINS a pipe. What makes it a
        # table is its second line being a delimiter row — that test is what keeps ordinary prose
        # containing a `|` out.
        if inside_fence or "|" not in line:
            n += 1
            continue
        block = []
        while n < len(lines) and "|" in lines[n] and lines[n].strip():
            block.append((n + 1, lines[n]))
            n += 1
        if len(block) < 2 or not re.match(r"^\s*\|?[\s:|-]+\|?\s*$", block[1][1].strip()) \
                or "-" not in block[1][1]:
            continue

        def cells(row):
            # An escaped \| is a literal, not a delimiter. Strip the outer pipes first.
            return len(re.split(r"(?<!\\)\|", row.strip().strip("|")))

        width = cells(block[1][1])
        for lineno, row in block:
            got = cells(row)
            # Only a row with MORE cells than the header loses content. GFM pads a short row with
            # empty cells and renders it fine, so flagging one is a false alarm — and flagging it
            # with the unescaped-pipe advice sends the author looking for a pipe that is not there.
            if got > width:
                problems.append(
                    f"{path}:{lineno}: table row has {got} cells, header has {width} — "
                    f"an unescaped `|` (write it as \\|) drops everything past cell {width}"
                )

if problems:
    print("\n".join(problems), file=sys.stderr)
    print(f"\n{len(problems)} markdown rendering problem(s)", file=sys.stderr)
    sys.exit(1)
print("markdown fences pair and every table row matches its header")
