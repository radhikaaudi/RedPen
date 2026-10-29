"""Render the synthetic sample class (samples/class.json) as photo-like handwritten answer sheets.

Run on macOS (uses its handwriting fonts):  python scripts/make_samples.py
Writes samples/sheets/*.jpg (neat), samples/sheets_messy/*.jpg (sloppy handwriting, badly
photographed) and samples/teacher_marks.csv. The generated files are committed,
so you only need this to change the sample class.
"""

import csv
import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
FONT_DIR = Path("/System/Library/Fonts/Supplemental")
FONTS = [
    (FONT_DIR / "Bradley Hand Bold.ttf", 0),
    (FONT_DIR / "ChalkboardSE.ttc", 0),
    (FONT_DIR / "Chalkboard.ttc", 0),
]
INKS = [(25, 45, 140), (20, 20, 30), (30, 60, 160), (45, 35, 110)]
W, H = 1240, 1754  # A4 at 150 dpi
LINE = 52
MARGIN_X = 150


def wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def write_line(draw, x, y, text, font, ink, rng):
    """Draw word by word with small baseline jitter so it looks handwritten."""
    for word in text.split(" "):
        draw.text((x + rng.uniform(-1, 1), y + rng.uniform(-3, 3)), word, font=font, fill=ink)
        x += draw.textlength(word + " ", font=font) + rng.uniform(-2, 3)
    return x


def render(student: dict, index: int) -> Image.Image:
    rng = random.Random(index * 7 + 3)
    font_path, font_index = FONTS[index % len(FONTS)]
    font = ImageFont.truetype(str(font_path), 34 if "Bradley" in font_path.name else 30, index=font_index)
    small = ImageFont.truetype(str(font_path), 30, index=font_index)
    ink = INKS[index % len(INKS)]

    page = Image.new("RGB", (W, H), (250, 248, 240))
    draw = ImageDraw.Draw(page)
    for y in range(200, H - 60, LINE):  # ruled lines
        draw.line([(0, y), (W, y)], fill=(170, 200, 230), width=2)
    draw.line([(MARGIN_X - 30, 0), (MARGIN_X - 30, H)], fill=(225, 120, 120), width=3)

    write_line(draw, MARGIN_X, 70, f"Name: {student['name']}", small, ink, rng)
    write_line(draw, MARGIN_X + 620, 70, "Class 8-B   Science UT-3", small, ink, rng)

    y = 200 - 44
    for qid, answer in student["answers"].items():
        if not answer:
            continue
        y += LINE
        lines = wrap(draw, answer, font, W - MARGIN_X - 90)
        draw.text((MARGIN_X - 105, y - 6), f"{qid}.", font=font, fill=ink)
        for n, line in enumerate(lines):
            end_x = write_line(draw, MARGIN_X, y - 6, line, font, ink, rng)
            # A crossed-out false start on some sheets, like real students do.
            if n == 0 and rng.random() < 0.25:
                sx = end_x + 10
                draw.text((sx, y - 6), "becau", font=font, fill=ink)
                wlen = draw.textlength("becau", font=font)
                draw.line([(sx - 4, y + 14), (sx + wlen + 4, y + 10)], fill=ink, width=4)
            y += LINE
        y += LINE // 2

    # Make it look like a phone photo: tilt, uneven light, slight blur and grain.
    page = page.rotate(rng.uniform(-1.6, 1.6), resample=Image.BICUBIC, expand=False, fillcolor=(120, 115, 105))
    shade = Image.linear_gradient("L").resize((W, H)).rotate(rng.choice([0, 90, 180, 270])).point(lambda v: 255 - v // 6)
    page = Image.composite(page, Image.new("RGB", (W, H), (200, 195, 180)), shade)
    page = page.filter(ImageFilter.GaussianBlur(0.6))
    noise = Image.effect_noise((W, H), 10).convert("RGB")
    page = Image.blend(page, noise, 0.04)
    return page


# ----------------------------------------------------------------------------- messy handwriting

MESSY_FONTS = [
    (Path("/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf"), 0, 40),
    (Path("/System/Library/Fonts/Noteworthy.ttc"), 0, 38),
    (Path("/System/Library/Fonts/Supplemental/Brush Script.ttf"), 0, 46),
    (Path("/System/Library/Fonts/MarkerFelt.ttc"), 1, 36),
    (Path("/System/Library/Fonts/Supplemental/Chalkduster.ttf"), 0, 32),
]


class Hand:
    """A sloppy writer: every letter gets its own size, tilt, height and spacing; lines drift."""

    def __init__(self, page: Image.Image, font_spec, ink, rng: random.Random, mess: float):
        path, index, size = font_spec
        self.page, self.ink, self.rng, self.mess = page, ink, rng, mess
        self.fonts = [ImageFont.truetype(str(path), int(size * s), index=index) for s in (0.86, 0.94, 1.0, 1.08, 1.18)]
        self.slant = rng.uniform(-9, 4)  # this writer's habitual lean
        self.size = size

    def glyph(self, ch: str, font) -> Image.Image:
        w = int(font.getlength(ch)) + 24
        h = int(self.size * 2.2)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((12, h * 0.2), ch, font=font, fill=self.ink + (255,), stroke_width=self.rng.choice([0, 0, 0, 1]), stroke_fill=self.ink + (255,))
        angle = self.slant + self.rng.gauss(0, 6 * self.mess)
        return img.rotate(angle, resample=Image.BICUBIC, expand=True)

    def write(self, x: float, y: float, text: str, max_x: float, line_h: float) -> tuple[float, float]:
        """Write text from (x, y), wrapping at max_x. Returns the position after the last word."""
        rng, start_x = self.rng, x
        drift = 0.0  # lines slowly climb or sink, as on unruled thinking
        for word in text.split():
            word_w = sum(self.fonts[2].getlength(c) for c in word) * 1.05
            if x + word_w > max_x and x > start_x:
                x, y = start_x + rng.uniform(-8, 14) * self.mess, y + line_h
                drift = 0.0
            # Occasionally scribble out a false start, the way students do.
            if rng.random() < 0.06 * self.mess:
                x = self.scribble(x, y, rng.choice(["teh", "becuse", "wat", "th", "sun"]))
            phase = rng.uniform(0, 6.3)
            for i, ch in enumerate(word):
                font = rng.choice(self.fonts if self.mess > 0.5 else self.fonts[1:4])
                g = self.glyph(ch, font)
                bob = math.sin(phase + i * 0.9) * 4 * self.mess + rng.gauss(0, 2.5 * self.mess)
                self.page.alpha_composite(g, (int(x) - 12, int(y + drift + bob - self.size * 0.45)))
                # Letters sometimes get written over a second time to "fix" them.
                if rng.random() < 0.025 * self.mess:
                    self.page.alpha_composite(self.glyph(ch, font), (int(x) - 10, int(y + drift + bob - self.size * 0.45 + 2)))
                x += font.getlength(ch) * rng.uniform(0.82, 1.08 + 0.12 * self.mess)
            x += font.getlength(" ") * rng.uniform(0.5, 1.6 + self.mess)
            drift += rng.uniform(-1.5, 2.5) * self.mess
        return x, y

    def scribble(self, x: float, y: float, word: str) -> float:
        draw = ImageDraw.Draw(self.page)
        w = self.fonts[2].getlength(word) * 1.1
        draw.text((x, y - self.size * 0.15), word, font=self.fonts[2], fill=self.ink + (255,))
        pts = []
        for k in range(int(w / 7) + 2):
            pts.append((x + k * 7 + self.rng.uniform(-2, 2), y + self.size * (0.35 if k % 2 else 0.85) + self.rng.uniform(-4, 4)))
        draw.line(pts, fill=self.ink + (255,), width=3)
        return x + w + 14


def warp(img: Image.Image, rng: random.Random, amount: float) -> Image.Image:
    """Wavy paper: shift thin horizontal and vertical strips along slow sine waves."""
    w, h = img.size
    out = img.copy()
    phase, period = rng.uniform(0, 6.3), rng.uniform(260, 420)
    for y in range(0, h, 6):
        dx = int(math.sin(phase + y / period * 6.28) * 6 * amount)
        out.paste(img.crop((0, y, w, y + 6)), (dx, y))
    img, out = out, out.copy()
    for x in range(0, w, 6):
        dy = int(math.sin(phase * 1.7 + x / period * 6.28) * 5 * amount)
        out.paste(img.crop((x, 0, x + 6, h)), (x, dy))
    return out


def phone_photo(page: Image.Image, rng: random.Random) -> Image.Image:
    """Photographed at an angle on a desk, with a shadow, poor focus and heavy JPEG compression."""
    w, h = page.size
    desk = Image.new("RGB", (w, h), (92, 78, 64))
    # Corners of the page as they land in the photo (perspective-ish quad).
    m = lambda: rng.uniform(20, 90)  # noqa: E731
    quad = (-m(), -m(), -m(), h + m(), w + m(), h + m() * 0.4, w + m() * 0.3, -m())
    photo = page.transform((w, h), Image.QUAD, quad, resample=Image.BICUBIC, fillcolor=(92, 78, 64))
    mask = Image.new("L", (w, h), 255).transform((w, h), Image.QUAD, quad, fillcolor=0)
    photo = Image.composite(photo, desk, mask)
    # Hand/phone shadow across one side.
    shadow = Image.linear_gradient("L").rotate(rng.choice([30, 120, 210, 300]), expand=False).resize((w, h))
    shadow = shadow.point(lambda v: 255 - int(max(0, v - 120) * 0.9))
    photo = Image.composite(photo, Image.new("RGB", (w, h), (40, 36, 30)), shadow)
    photo = ImageEnhance.Contrast(photo).enhance(rng.uniform(0.72, 0.85))
    photo = photo.filter(ImageFilter.GaussianBlur(rng.uniform(1.0, 1.5)))
    noise = Image.effect_noise((w, h), 30).convert("RGB")
    photo = Image.blend(photo, noise, 0.07)
    return photo.resize((int(w * 0.8), int(h * 0.8)))


def render_messy(student: dict, index: int) -> Image.Image:
    rng = random.Random(index * 13 + 5)
    mess = 0.65 + 0.35 * (index % 4) / 3  # some students are messier than others
    ink = INKS[(index + 1) % len(INKS)]
    page = Image.new("RGBA", (W, H), (246, 243, 232, 255))
    draw = ImageDraw.Draw(page)
    for y in range(200, H - 60, LINE):
        draw.line([(0, y), (W, y)], fill=(175, 200, 228, 255), width=2)
    draw.line([(MARGIN_X - 30, 0), (MARGIN_X - 30, H)], fill=(225, 125, 125, 255), width=3)
    hand = Hand(page, MESSY_FONTS[index % len(MESSY_FONTS)], ink, rng, mess)

    hand.write(MARGIN_X - 20, 70, f"Name - {student['name']}", W - 500, LINE)
    hand.write(W - 470, 76, "8 B  sci UT3", W - 40, LINE)

    y = 200 - 30.0
    for qid, answer in student["answers"].items():
        if not answer:
            continue
        y += LINE * rng.uniform(0.9, 1.4)
        Hand(page, MESSY_FONTS[index % len(MESSY_FONTS)], ink, rng, mess * 0.6).write(MARGIN_X - 118, y, qid.lower() if rng.random() < 0.4 else qid, MARGIN_X, LINE)
        _, y = hand.write(MARGIN_X + rng.uniform(-10, 10), y, answer, W - 60 - rng.uniform(0, 80), LINE * rng.uniform(0.95, 1.15))
        y += LINE * rng.uniform(0.5, 1.0)

    # Ink blots and smudges.
    for _ in range(rng.randint(1, 3)):
        bx, by, r = rng.uniform(150, W - 100), rng.uniform(220, y + 40), rng.uniform(4, 10)
        draw.ellipse([bx - r, by - r * 0.7, bx + r, by + r * 0.7], fill=ink + (200,))
    page = warp(page.convert("RGB"), rng, mess)
    return phone_photo(page, rng)


def main() -> None:
    data = json.loads((SAMPLES / "class.json").read_text())
    out = SAMPLES / "sheets"
    out.mkdir(exist_ok=True)
    messy_out = SAMPLES / "sheets_messy"
    messy_out.mkdir(exist_ok=True)
    rows = []
    for i, student in enumerate(data["students"]):
        slug = student["name"].lower().replace(" ", "_")
        render(student, i).save(out / f"{slug}.jpg", quality=82)
        render_messy(student, i).save(messy_out / f"{slug}.jpg", quality=55)
        for qid, mark in student["marks"].items():
            rows.append({"student": student["name"], "sheet": f"{slug}.jpg", "question_id": qid, "teacher_marks": mark})
        print("wrote", slug)
    with open(SAMPLES / "teacher_marks.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["student", "sheet", "question_id", "teacher_marks"])
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
