"""Screenshot → text with the `tesseract` binary (apt install tesseract-ocr). No Python OCR dependency."""

import re
import subprocess

NUMBER = re.compile(r"\d[\d,]*(?:\.\d{1,2})?")


class OcrError(Exception):
    pass


def image_text(data: bytes) -> str:
    """OCR an image into one string, lines joined with ". " so the SMS regexes see sentence ends.

    Tesseract has no ₹ and reads it as junk ("€450", "~450", sometimes "2450"). Payment apps show the amount
    as the biggest text on screen, so the tallest number is rewritten as "₹<number>" for the parser.
    ponytail: a ₹ misread as a digit stays wrong; the Inbox asks to check, and the bank SMS (same UPI ref) corrects it.
    """
    try:
        out = subprocess.run(["tesseract", "stdin", "stdout", "tsv"], input=data, capture_output=True, timeout=60)
    except FileNotFoundError:
        raise OcrError("tesseract isn't installed on the server")
    except subprocess.TimeoutExpired:
        raise OcrError("OCR took too long")
    if out.returncode:
        raise OcrError(out.stderr.decode(errors="replace").strip()[-200:] or "OCR failed")
    lines: dict[tuple, list] = {}  # (block, paragraph, line) -> [[height, word], …]
    for row in out.stdout.decode(errors="replace").splitlines()[1:]:
        f = row.split("\t")
        if len(f) == 12 and f[0] == "5" and f[11].strip():
            lines.setdefault((int(f[2]), int(f[3]), int(f[4])), []).append([int(f[9]), f[11].strip()])
    numbers = [w for ws in lines.values() for w in ws if NUMBER.search(w[1])]
    if numbers:
        biggest = max(numbers, key=lambda w: w[0])
        biggest[1] = "₹" + NUMBER.search(biggest[1]).group()
    return ". ".join(" ".join(w for _, w in ws).rstrip(".") for ws in lines.values())
