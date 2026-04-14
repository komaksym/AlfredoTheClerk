"""Tests for geometric PDF parser (words → lines → blocks → sub-blocks)."""

import pdfplumber

from src.input_processing.parse import (
    REPO_ROOT_PATH,
    Word,
    Line,
    Block,
    check_same_line,
    parse_words,
    parse_lines,
    calc_largest_line_gap,
    parse_blocks,
    calculate_inblock_gaps,
    get_gutters,
    parse_sub_blocks,
    parse_data,
)


def make_word(
    text: str, x0: float, x1: float, top: float, bottom: float
) -> Word:
    """Create a Word with auto-computed height."""
    return Word(text, x0, x1, top, bottom)


def make_line(words: list[Word]) -> Line:
    """Create a Line with bbox derived from its words."""
    return Line(
        words=words,
        x0=min(w.x0 for w in words),
        x1=max(w.x1 for w in words),
        top=min(w.top for w in words),
        bottom=max(w.bottom for w in words),
    )


def make_block(lines: list[Line]) -> Block:
    """Create a Block with bbox derived from its lines."""
    return Block(
        lines=lines,
        x0=min(line.x0 for line in lines),
        x1=max(line.x1 for line in lines),
        top=min(line.top for line in lines),
        bottom=max(line.bottom for line in lines),
    )


class TestCheckSameLine:
    """Y-overlap line detection with adaptive threshold."""

    def test_same_line_full_overlap(self):
        w1 = make_word("a", 0, 10, 100, 112)
        w2 = make_word("b", 20, 30, 100, 112)
        assert check_same_line(w1, w2) is True

    def test_same_line_partial_overlap(self):
        w1 = make_word("a", 0, 10, 100, 112)
        w2 = make_word("b", 20, 30, 102, 114)
        # overlap=10, threshold=6
        assert check_same_line(w1, w2) is True

    def test_different_lines_no_overlap(self):
        w1 = make_word("a", 0, 10, 100, 112)
        w2 = make_word("b", 0, 10, 130, 142)
        assert check_same_line(w1, w2) is False

    def test_different_lines_minimal_overlap(self):
        """Tall word barely clips into small word — not same line."""
        w1 = make_word("a", 0, 10, 100, 112)  # height 12
        w2 = make_word("b", 0, 10, 108, 124)  # height 16
        # overlap=4, threshold=6
        assert check_same_line(w1, w2) is False

    def test_different_font_sizes_same_line(self):
        """Mixed font sizes with sufficient overlap — same line."""
        w1 = make_word("big", 0, 50, 100, 124)  # height 24
        w2 = make_word("small", 60, 80, 106, 118)  # height 12
        # overlap=12, threshold=6
        assert check_same_line(w1, w2) is True


class TestParseWords:
    """Conversion from pdfplumber dicts to Word dataclasses."""

    def test_basic(self):
        raw = [
            {
                "text": "hello",
                "x0": 10,
                "x1": 50,
                "top": 100,
                "bottom": 112,
                "height": 12,
            }
        ]
        words = parse_words(raw)
        assert len(words) == 1
        assert words[0].text == "hello"
        assert words[0].x0 == 10

    def test_empty(self):
        assert parse_words([]) == []


class TestParseLines:
    """Sequential word grouping by y-overlap."""

    def test_single_line(self):
        words = [
            make_word("hello", 10, 50, 100, 112),
            make_word("world", 60, 100, 100, 112),
        ]
        lines = parse_lines(words)
        assert len(lines) == 1
        assert len(lines[0].words) == 2

    def test_two_lines(self):
        words = [
            make_word("line1", 10, 50, 100, 112),
            make_word("line2", 10, 50, 130, 142),
        ]
        lines = parse_lines(words)
        assert len(lines) == 2
        assert lines[0].words[0].text == "line1"
        assert lines[1].words[0].text == "line2"

    def test_single_word(self):
        words = [make_word("alone", 10, 50, 100, 112)]
        lines = parse_lines(words)
        assert len(lines) == 1
        assert lines[0].words[0].text == "alone"

    def test_empty(self):
        assert parse_lines([]) == []


class TestCalcLargestLineGap:
    """Block-break threshold from sorted gap distribution."""

    def test_basic(self):
        lines = [
            make_line([make_word("a", 10, 50, 100, 112)]),
            make_line([make_word("b", 10, 50, 116, 128)]),
            make_line([make_word("c", 10, 50, 180, 192)]),
        ]
        # gaps: [4, 52] → threshold = (4+52)/2 = 28
        assert calc_largest_line_gap(lines) == 28.0


class TestParseBlocks:
    """Line grouping into blocks by y-gap thresholding."""

    def test_two_blocks(self):
        lines = [
            make_line([make_word("a", 10, 50, 100, 112)]),
            make_line([make_word("b", 10, 50, 116, 128)]),
            make_line([make_word("c", 10, 50, 180, 192)]),
            make_line([make_word("d", 10, 50, 196, 208)]),
        ]
        # gaps: [4, 52, 4] → threshold=28 → break at gap=52
        blocks = parse_blocks(lines)
        assert len(blocks) == 2
        assert len(blocks[0].lines) == 2
        assert len(blocks[1].lines) == 2


class TestCalculateInblockGaps:
    """Inter-word gap detection using 10% block-width threshold."""

    def test_detects_gutter(self):
        """Two-column block: gap between columns exceeds 10% of block width."""
        lines = [
            make_line(
                [
                    make_word("left1", 50, 140, 100, 112),
                    make_word("right1", 300, 370, 100, 112),
                ]
            ),
            make_line(
                [
                    make_word("left2", 50, 160, 116, 128),
                    make_word("right2", 300, 385, 116, 128),
                ]
            ),
        ]
        block = make_block(lines)
        gaps = calculate_inblock_gaps(block)
        assert 0 in gaps
        assert 1 in gaps
        assert gaps[0] == [(140, 300)]
        assert gaps[1] == [(160, 300)]

    def test_no_gutter(self):
        """Single-column: word spacing below 10% threshold."""
        lines = [
            make_line(
                [
                    make_word("hello", 50, 90, 100, 112),
                    make_word("world", 95, 135, 100, 112),
                ]
            ),
        ]
        block = make_block(lines)
        assert calculate_inblock_gaps(block) == {}


class TestGetGutters:
    """Cross-line gap overlap to find column separators."""

    def test_valid_gutter(self):
        """Gaps in both lines overlap → valid gutter."""
        in_block_gaps = {
            0: [(140, 300)],
            1: [(160, 300)],
        }
        gutters = get_gutters(in_block_gaps, num_lines=2)
        assert len(gutters) == 1
        # Tightened to intersection
        assert gutters[0] == (160, 300)

    def test_gap_in_minority_of_lines(self):
        """Gap in 1 of 4 lines (<50%) → rejected."""
        in_block_gaps = {
            0: [(140, 300)],
        }
        assert get_gutters(in_block_gaps, num_lines=4) == []

    def test_two_gutters(self):
        """Three-column layout produces two gutters."""
        in_block_gaps = {
            0: [(100, 180), (280, 350)],
            1: [(110, 175), (285, 345)],
        }
        gutters = get_gutters(in_block_gaps, num_lines=2)
        assert len(gutters) == 2
        assert gutters[0][0] < gutters[1][0]

    def test_empty(self):
        assert get_gutters({}, num_lines=3) == []


class TestParseSubBlocks:
    """Block splitting into sub-blocks by x-gutters."""

    def test_two_column_split(self):
        """Seller/buyer side-by-side → 2 sub-blocks."""
        lines = [
            make_line(
                [
                    make_word("Sprzedawca", 50, 140, 100, 112),
                    make_word("Nabywca", 300, 370, 100, 112),
                ]
            ),
            make_line(
                [
                    make_word("ACME", 50, 90, 116, 128),
                    make_word("Klient", 300, 350, 116, 128),
                ]
            ),
            make_line(
                [
                    make_word("NIP:123", 50, 140, 132, 144),
                    make_word("NIP:098", 300, 390, 132, 144),
                ]
            ),
        ]
        block = make_block(lines)
        subs = parse_sub_blocks(block)
        assert len(subs) == 2

        left_texts = [w.text for w in subs[0].words]
        right_texts = [w.text for w in subs[1].words]
        assert "Sprzedawca" in left_texts
        assert "Nabywca" in right_texts
        assert "ACME" in left_texts
        assert "Klient" in right_texts

    def test_single_column_no_split(self):
        """No gutter detected → single sub-block."""
        lines = [
            make_line(
                [
                    make_word("Faktura", 50, 100, 100, 112),
                    make_word("VAT", 105, 130, 100, 112),
                ]
            ),
        ]
        block = make_block(lines)
        subs = parse_sub_blocks(block)
        assert len(subs) == 1
        assert len(subs[0].words) == 2

    def test_three_column_split(self):
        """Three-column layout → 3 sub-blocks."""
        lines = [
            make_line(
                [
                    make_word("A", 10, 40, 100, 112),
                    make_word("B", 200, 230, 100, 112),
                    make_word("C", 400, 430, 100, 112),
                ]
            ),
            make_line(
                [
                    make_word("A2", 10, 45, 116, 128),
                    make_word("B2", 200, 240, 116, 128),
                    make_word("C2", 400, 440, 116, 128),
                ]
            ),
        ]
        block = make_block(lines)
        subs = parse_sub_blocks(block)
        assert len(subs) == 3
        assert subs[0].words[0].text == "A"
        assert subs[1].words[0].text == "B"
        assert subs[2].words[0].text == "C"


class TestParseData:
    """End-to-end pipeline against the real synthetic invoice."""

    def test_synthetic_invoice_splits_seller_buyer(self):
        pdf_path = (
            REPO_ROOT_PATH
            / "data/synthetic_data/FV2026_11_390_seller_buyer_block_v1.pdf"
        )
        with pdfplumber.open(pdf_path) as pdf:
            result = parse_data(pdf)

        # One list of sub-blocks per block
        assert len(result) >= 2

        all_texts = [
            w.text
            for block_subs in result
            for sb in block_subs
            for w in sb.words
        ]
        assert "Sprzedawca" in all_texts
        assert "Nabywca" in all_texts

        # The seller/buyer block should split into 2 sub-blocks (left/right columns)
        seller_buyer_block = next(
            block_subs
            for block_subs in result
            if any(
                w.text == "Sprzedawca" for sb in block_subs for w in sb.words
            )
        )
        assert len(seller_buyer_block) == 2

        left_texts = [w.text for w in seller_buyer_block[0].words]
        right_texts = [w.text for w in seller_buyer_block[1].words]
        assert "Sprzedawca" in left_texts
        assert "Nabywca" in right_texts
