"""Geometric PDF parser: words → lines → blocks → sub-blocks.

Clusters pdfplumber word-level extractions into hierarchical
layout structures using only bounding-box geometry (y-overlap
for lines, y-gap for blocks, x-gutter for sub-blocks).
"""

import pdfplumber
from pdfplumber.pdf import PDF
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

    @property
    def height(self) -> float:
        return self.bottom - self.top


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


@dataclass(frozen=True)
class TableCell:
    """One cell extracted from a bordered PDF table.

    ``text`` is ``None`` when pdfplumber reports the cell as empty.
    ``bbox`` carries the cell's ``(x0, top, x1, bottom)`` so downstream
    evidence can cite the exact region on the page.
    """

    text: str | None
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class ParsedTable:
    """One bordered table and its cells, as seen by pdfplumber."""

    bbox: tuple[float, float, float, float]
    rows: list[list[TableCell]]


@dataclass(frozen=True)
class ParsedDocument:
    """Single-page parse output: word-level sub-blocks plus bordered tables.

    Bundles the two geometry layers extracted from one PDF so downstream
    code can take a single argument instead of running ``parse_data`` and
    ``parse_tables`` independently.
    """

    sub_blocks: list[list[SubBlock]]
    tables: list[ParsedTable]


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
        Word(w["text"], w["x0"], w["x1"], w["top"], w["bottom"]) for w in text
    ]


def bbox_of(items: list) -> tuple[float, float, float, float]:
    """Return (x0, x1, top, bottom) enveloping all items."""

    x0 = min(it.x0 for it in items)
    x1 = max(it.x1 for it in items)
    top = min(it.top for it in items)
    bottom = max(it.bottom for it in items)
    return x0, x1, top, bottom


def parse_lines(words: list[Word]) -> list[Line]:
    """Group words into lines by y-overlap with the anchor word."""

    lines: list[Line] = []
    i = 0
    while i < len(words):
        anchor = words[i]
        group = [anchor]

        j = i + 1
        while j < len(words) and check_same_line(anchor, words[j]):
            group.append(words[j])
            j += 1

        x0, x1, top, bottom = bbox_of(group)
        lines.append(Line(words=group, x0=x0, x1=x1, top=top, bottom=bottom))
        i = j

    return lines


def calc_largest_line_gap(lines: list[Line]) -> float:
    """Compute block-break threshold as the midpoint of the largest jump
    between consecutive sorted gaps.

    Sorting groups gaps into clusters (e.g. line spacing vs block
    separators); the biggest jump marks the natural boundary between them.
    """

    gaps = sorted(
        lines[i + 1].top - lines[i].bottom for i in range(len(lines) - 1)
    )

    if len(gaps) < 2:
        raise ValueError(
            f"Invoice must have at least 3 lines for block detection, got {len(gaps)}"
        )

    largest_gap = 0
    first_gap, second_gap = 0, 0
    for i in range(1, len(gaps)):
        if gaps[i] - gaps[i - 1] > largest_gap:
            largest_gap = gaps[i] - gaps[i - 1]
            first_gap, second_gap = gaps[i - 1], gaps[i]

    return (first_gap + second_gap) / 2


def parse_blocks(lines: list[Line]) -> list[Block]:
    """Group lines into blocks by y-gap thresholding."""

    if not lines:
        return []

    threshold = calc_largest_line_gap(lines)
    blocks: list[Block] = []
    i = 0
    while i < len(lines):
        group = [lines[i]]

        j = i + 1
        while j < len(lines):
            gap = lines[j].top - lines[j - 1].bottom
            if gap >= threshold:
                break
            group.append(lines[j])
            j += 1

        x0, x1, top, bottom = bbox_of(group)
        blocks.append(Block(lines=group, x0=x0, x1=x1, top=top, bottom=bottom))
        i = j

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


_TABLE_LINE_SETTINGS = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
}


def parse_tables(pdf_file: PDF) -> list[ParsedTable]:
    """Return every bordered table on a single-page PDF.

    Uses pdfplumber's ``lines`` detection strategy so only tables
    with real drawn borders are recognized. The rendered M4 line-items
    table uses ``border: 0.3mm solid #000`` precisely to make this
    deterministic.
    """

    if len(pdf_file.pages) != 1:
        raise ValueError(
            f"Expected single-page PDF, got {len(pdf_file.pages)} pages"
        )

    page = pdf_file.pages[0]
    detected = page.find_tables(table_settings=_TABLE_LINE_SETTINGS)
    if not detected:
        return []

    texts_per_table = page.extract_tables(table_settings=_TABLE_LINE_SETTINGS)

    parsed: list[ParsedTable] = []
    for table, text_rows in zip(detected, texts_per_table, strict=True):
        rows: list[list[TableCell]] = []
        for row_obj, text_row in zip(table.rows, text_rows, strict=True):
            row_cells: list[TableCell] = []
            for cell_bbox, text in zip(row_obj.cells, text_row, strict=True):
                row_cells.append(TableCell(text=text, bbox=cell_bbox))
            rows.append(row_cells)
        parsed.append(ParsedTable(bbox=table.bbox, rows=rows))

    return parsed


def parse_data(pdf_file: PDF) -> ParsedDocument:
    """Run the full parse pipeline on a single-page PDF.

    Extracts two geometry layers in one pass:

    * words → lines (y-overlap) → blocks (y-gap) → sub-blocks (x-gutter)
    * bordered tables via pdfplumber's ``lines`` strategy

    Both are bundled into one :class:`ParsedDocument` so downstream
    extractors can consume a single value.
    """

    if len(pdf_file.pages) != 1:
        raise ValueError(
            f"Expected single-page PDF, got {len(pdf_file.pages)} pages"
        )

    page = pdf_file.pages[0]
    text = page.extract_words()

    words = parse_words(text)
    lines = parse_lines(words)
    blocks = parse_blocks(lines)
    sub_blocks = [parse_sub_blocks(block) for block in blocks]

    tables = parse_tables(pdf_file)

    return ParsedDocument(sub_blocks=sub_blocks, tables=tables)


def main() -> None:
    pdf_sample = (
        REPO_ROOT_PATH
        / "data/synthetic_data/FV2026_11_390_seller_buyer_block_v1.pdf"
    )

    with pdfplumber.open(pdf_sample) as pdf:
        document = parse_data(pdf)
        print(document)


if __name__ == "__main__":
    main()
