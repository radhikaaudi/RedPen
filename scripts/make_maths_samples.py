"""Render the maths sample class (samples/maths/class.json) as handwritten answer sheets.

Run on macOS (uses its handwriting fonts):  python scripts/make_maths_samples.py
Writes samples/maths/sheets/*.jpg. Answers listed under a student's "illegible" key are written as
a smudged scribble on purpose, to show Redpen handing an unreadable answer to the teacher.
"""

import json
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from make_samples import FONTS, H, INKS, LINE, MARGIN_X, SAMPLES, W, Hand, wrap, write_line

MATHS = SAMPLES / "maths"


def render(student: dict, header: str, index: int) -> Image.Image:
    rng = random.Random(index * 11 + 2)
    font_path, font_index = FONTS[index % len(FONTS)]
    font = ImageFont.truetype(str(font_path), 34 if "Bradley" in font_path.name else 30, index=font_index)
    small = ImageFont.truetype(str(font_path), 30, index=font_index)
    ink = INKS[index % len(INKS)]

    page = Image.new("RGBA", (W, H), (250, 248, 240, 255))
    draw = ImageDraw.Draw(page)
    for y in range(200, H - 60, LINE):
        draw.line([(0, y), (W, y)], fill=(170, 200, 230, 255), width=2)
    draw.line([(MARGIN_X - 30, 0), (MARGIN_X - 30, H)], fill=(225, 120, 120, 255), width=3)

    write_line(draw, MARGIN_X, 70, f"Name: {student['name']}", small, ink, rng)
    write_line(draw, MARGIN_X + 620, 70, header, small, ink, rng)

    y = 200 - 44
    for qid, answer in student["answers"].items():
        y += LINE
        draw.text((MARGIN_X - 105, y - 6), f"{qid}.", font=font, fill=ink)
        if qid in student.get("illegible", []):
            # Rushed, tiny, overwritten scrawl, then smudged — unreadable even to a person.
            top = y - 30
            hand = Hand(page, (font_path, font_index, 22), ink, rng, 2.6)
            _, end_y = hand.write(MARGIN_X, y - 6, answer, W - 140, LINE * 0.55)
            Hand(page, (font_path, font_index, 22), ink, rng, 2.6).write(MARGIN_X + 9, y - 2, answer, W - 140, LINE * 0.55)
            box = (MARGIN_X - 10, top, W - 60, int(end_y) + 70)
            page.paste(page.crop(box).filter(ImageFilter.GaussianBlur(4)), box[:2])
            y = int(end_y) + LINE
        else:
            for line in wrap(draw, answer, font, W - MARGIN_X - 90):
                write_line(draw, MARGIN_X, y - 6, line, font, ink, rng)
                y += LINE
        y += LINE // 2

    page = page.convert("RGB").rotate(rng.uniform(-1.4, 1.4), resample=Image.BICUBIC, fillcolor=(120, 115, 105))
    shade = Image.linear_gradient("L").resize((W, H)).rotate(rng.choice([0, 90, 180, 270])).point(lambda v: 255 - v // 6)
    page = Image.composite(page, Image.new("RGB", (W, H), (200, 195, 180)), shade)
    page = page.filter(ImageFilter.GaussianBlur(0.6))
    return Image.blend(page, Image.effect_noise((W, H), 10).convert("RGB"), 0.04)


def main() -> None:
    data = json.loads((MATHS / "class.json").read_text())
    out = MATHS / "sheets"
    out.mkdir(exist_ok=True)
    for i, student in enumerate(data["students"]):
        slug = student["name"].lower().replace(" ", "_")
        render(student, data["header"], i).save(out / f"{slug}.jpg", quality=82)
        print("wrote", slug)


if __name__ == "__main__":
    main()
