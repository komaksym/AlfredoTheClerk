"""Geometric PDF parser: words → lines → blocks → sub-blocks.

Clusters pdfplumber word-level extractions into hierarchical
layout structures using only bounding-box geometry (y-overlap
for lines, y-gap for blocks, x-gutter for sub-blocks).
"""

import pdfplumber
from pathlib import Path
from dataclasses import dataclass


REPO_ROOT_PATH = Path(__file__).resolve().parents[2]


@dataclass
class Word:
    """Single word extracted from PDF with bounding box."""

    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    height: float


@dataclass
class Line:
    """Horizontal group of words sharing vertical overlap."""

    words: list[Word]
    x0: float
    x1: float
    top: float
    bottom: float


@dataclass
class Block:
    """Vertical group of lines separated by large y-gaps."""

    lines: list[Line]
    x0: float
    x1: float
    top: float
    bottom: float


@dataclass
class SubBlock:
    """Column within a block, split by x-gutters."""

    words: list[Word]
    x0: float
    x1: float
    top: float
    bottom: float


def normalize_text(text: str) -> str:
    return text.lower().strip()


def check_same_line(w1: Word, w2: Word) -> bool:
    """Check if two words share enough vertical overlap to be on the same line.

    Uses interval overlap on the y-axis rather than comparing a single
    y-coordinate, so it adapts to mixed font sizes and OCR jitter.
    """
    overlap = min(w1.bottom, w2.bottom) - max(w1.top, w2.top)
    return overlap > 0.5 * min(w1.height, w2.height)


def parse_words(text: list[dict]) -> list[Word]:
    """Convert raw pdfplumber word dicts to Word dataclasses."""
    return [
        Word(w["text"], w["x0"], w["x1"], w["top"], w["bottom"], w["height"])
        for w in text
    ]


def parse_lines(words: list[Word]) -> list[Line]:
    """Group words into lines by y-overlap.

    Walks words sequentially; consecutive words that overlap
    vertically with the anchor word are merged into one line.
    """
    lines: list[Line] = []

    i = 0
    while i < len(words):
        cur_word = words[i]
        line_words = [cur_word]

        min_x0 = cur_word.x0
        max_x1 = cur_word.x1
        min_top = cur_word.top
        max_bottom = cur_word.bottom

        j = i + 1
        while j < len(words):
            cand_word = words[j]
            if check_same_line(cur_word, cand_word):
                line_words.append(cand_word)
                min_x0 = min(min_x0, cand_word.x0)
                max_x1 = max(max_x1, cand_word.x1)
                min_top = min(min_top, cand_word.top)
                max_bottom = max(max_bottom, cand_word.bottom)
                j += 1
            else:
                break

        i = j
        lines.append(
            Line(
                words=line_words,
                x0=min_x0,
                x1=max_x1,
                top=min_top,
                bottom=max_bottom,
            )
        )

    return lines


def check_same_block(
    cur_line: Line, next_line: Line, largest_between_line_gap: float
) -> bool:
    """True if the y-gap between two lines is below the block-break threshold."""
    between_line_gap = next_line.top - cur_line.bottom
    return between_line_gap < largest_between_line_gap


def calc_largest_line_gap(lines: list[Line]) -> float:
    """Compute block-break threshold as the average of the two largest gaps.

    Sorted gaps let us separate normal line spacing from section breaks.
    """
    gaps: list[float] = []
    for i in range(len(lines) - 1):
        gap = lines[i + 1].top - lines[i].bottom
        gaps.append(gap)

    gaps.sort()
    return (gaps[-2] + gaps[-1]) / 2


def parse_blocks(lines: list[Line]) -> list[Block]:
    """Group lines into blocks by y-gap thresholding."""
    blocks: list[Block] = []
    largest_between_line_gap = calc_largest_line_gap(lines)

    i = 0
    while i < len(lines):
        cur_line = lines[i]
        block_lines = [cur_line]

        min_x0 = cur_line.x0
        max_x1 = cur_line.x1
        min_top = cur_line.top
        max_bottom = cur_line.bottom

        j = i + 1
        while j < len(lines):
            cand_line = lines[j]
            if check_same_block(cur_line, cand_line, largest_between_line_gap):
                block_lines.append(cand_line)
                cur_line = cand_line
                min_x0 = min(min_x0, cand_line.x0)
                max_x1 = max(max_x1, cand_line.x1)
                min_top = min(min_top, cand_line.top)
                max_bottom = max(max_bottom, cand_line.bottom)
                j += 1
            else:
                break

        i = j
        blocks.append(
            Block(
                lines=block_lines,
                x0=min_x0,
                x1=max_x1,
                top=min_top,
                bottom=max_bottom,
            )
        )

    return blocks


def calculate_inblock_gaps(
    block: Block,
) -> dict[int, list[tuple[float, float]]]:
    """Find wide inter-word gaps per line that could be column gutters.

    A gap qualifies if it's >= 10% of the block width (relative
    threshold so it works regardless of page size or units).
    """
    block_width = block.x1 - block.x0
    gutter_threshold = block_width * 0.1
    in_block_gaps: dict[int, list[tuple[float, float]]] = {}

    for idx, line in enumerate(block.lines):
        line_gaps: list[tuple[float, float]] = []
        for i in range(len(line.words) - 1):
            cur_word = line.words[i]
            next_word = line.words[i + 1]

            between_word_gap = next_word.x0 - cur_word.x1
            if between_word_gap >= gutter_threshold:
                line_gaps.append((cur_word.x1, next_word.x0))
        if line_gaps:
            in_block_gaps[idx] = line_gaps

    return in_block_gaps


def get_gutters(
    in_block_gaps: dict[int, list[tuple[float, float]]], num_lines: int
) -> list[tuple[float, float]]:
    """Find x-gaps that overlap across >=50% of lines in the block.

    Merges overlapping gap intervals across lines by tightening
    to their intersection (max of starts, min of ends). A gutter
    is valid only if it spans the majority of lines.
    """
    all_gaps: list[tuple[tuple[float, float], int]] = []
    for line_idx, gaps in in_block_gaps.items():
        for gap in gaps:
            all_gaps.append((gap, line_idx))

    if not all_gaps:
        return []

    # Each candidate: [tightened_start, tightened_end, {line indices}]
    gutters: list[list] = []
    for gap, line_idx in all_gaps:
        merged = False
        for gutter in gutters:
            overlap = min(gap[1], gutter[1]) - max(gap[0], gutter[0])
            if overlap > 0:
                # Tighten to intersection
                gutter[0] = max(gap[0], gutter[0])
                gutter[1] = min(gap[1], gutter[1])
                gutter[2].add(line_idx)
                merged = True
                break
        if not merged:
            gutters.append([gap[0], gap[1], {line_idx}])

    min_lines = num_lines * 0.5
    valid_gutters = [(g[0], g[1]) for g in gutters if len(g[2]) >= min_lines]
    valid_gutters.sort(key=lambda g: g[0])
    return valid_gutters


def parse_sub_blocks(block: Block) -> list[SubBlock]:
    """Split a block into sub-blocks by x-gutters.

    N gutters produce N+1 sub-blocks (columns). Words are assigned
    to columns by their x-center position.
    """
    in_block_gaps = calculate_inblock_gaps(block)
    gutters = get_gutters(in_block_gaps, len(block.lines))

    if not gutters:
        return [
            SubBlock(
                words=[w for line in block.lines for w in line.words],
                x0=block.x0,
                x1=block.x1,
                top=block.top,
                bottom=block.bottom,
            )
        ]

    # Column boundaries: [block.x0, gutter1.start], [gutter1.end, gutter2.start], ...
    boundaries: list[tuple[float, float]] = []
    boundaries.append((block.x0, gutters[0][0]))
    for i in range(len(gutters) - 1):
        boundaries.append((gutters[i][1], gutters[i + 1][0]))
    boundaries.append((gutters[-1][1], block.x1))

    sub_blocks: list[SubBlock] = []
    for col_left, col_right in boundaries:
        col_words: list[Word] = []
        for line in block.lines:
            for word in line.words:
                word_center = (word.x0 + word.x1) / 2
                if col_left <= word_center <= col_right:
                    col_words.append(word)
        if col_words:
            sub_blocks.append(
                SubBlock(
                    words=col_words,
                    x0=min(w.x0 for w in col_words),
                    x1=max(w.x1 for w in col_words),
                    top=min(w.top for w in col_words),
                    bottom=max(w.bottom for w in col_words),
                )
            )

    return sub_blocks


def main() -> None:
    pdf_sample = (
        REPO_ROOT_PATH
        / "data/synthetic_data/FV2026_11_390_seller_buyer_block_v1.pdf"
    )

    with pdfplumber.open(pdf_sample) as pdf:
        page = pdf.pages[0]
        text = page.extract_words()

        words = parse_words(text)
        lines = parse_lines(words)
        blocks = parse_blocks(lines)
        sub_blocks = []
        for block in blocks:
            sub_blocks.append(parse_sub_blocks(block))


if __name__ == "__main__":
    main()
