import pdfplumber
from pathlib import Path
from dataclasses import dataclass


REPO_ROOT_PATH = Path(__file__).resolve().parents[2]


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    height: float


@dataclass
class Line:
    words: list[Word]
    x0: float
    x1: float
    top: float
    bottom: float


def normalize_text(text):
    return text.lower().strip()


def check_same_line(w1, w2):
    overlap = min(w1.bottom, w2.bottom) - max(w1.top, w2.top)
    same_line = overlap > 0.5 * min(w1.height, w2.height)
    return same_line


def parse_words(text):
    words = [
        Word(w["text"], w["x0"], w["x1"], w["top"], w["bottom"], w["height"])
        for w in text
    ]
    return words


def parse_lines(words):
    lines = []

    i = 0
    while i < len(words):
        cur_word = words[i]
        # Words in a single line
        line_words = [cur_word]

        # Bounding Box coords
        min_x0 = float("inf")
        max_x1 = float("-inf")
        min_top = float("inf")
        max_bottom = float("-inf")

        # Seach for candidates starting from the next word
        j = i + 1
        # Iter over candidates
        while j < len(words):
            cand_word = words[j]
            # If same line
            if check_same_line(cur_word, cand_word):
                line_words.append(cand_word)

                # BBX coords
                min_x0 = min(min_x0, cand_word.x0)
                max_x1 = max(max_x1, cand_word.x1)
                min_top = min(min_top, cand_word.top)
                max_bottom = max(max_bottom, cand_word.bottom)

                # Search for next candidate
                j += 1

            # Next line, reset
            else:
                break
        # Continue to build lines from the new word which wasn't recognized in the same line
        i = j
        # Add line to lines
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


def parse_blocks(lines):
    blocks = []

    return blocks


def main():
    pdf_sample = (
        REPO_ROOT_PATH
        / "data/synthetic_data/FV2026_11_390_seller_buyer_block_v1.pdf"
    )

    with pdfplumber.open(pdf_sample) as pdf:
        page = pdf.pages[0]
        text = page.extract_words()

        # Populate words
        words = parse_words(text)
        # Populate lines
        lines = parse_lines(words)
        # Populate blocks
        print(lines)


if __name__ == "__main__":
    main()
