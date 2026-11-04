"""Build deliverables/cover.png (2000x1500, 4:3) with PIL, in the csv-cleaning-tool cover layout:
title + subtitle, one real screenshot of the app in a rounded panel, three number cards, demo badge.

The only UI pixels are a crop of docs/evidence/a27/03_conflict_blocked.png (a real-window A27 screenshot);
nothing in it is redrawn. The numbers come from docs/evidence/a27/a27_checks.json and the journals.
"""
import os
from PIL import Image, ImageDraw, ImageFont

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOT = os.path.join(REPO, "docs", "evidence", "a27", "03_conflict_blocked.png")
OUT = os.path.join(REPO, "deliverables", "cover.png")
W, H = 2000, 1500
F = r"C:\Windows\Fonts"


def font(n, s):
    return ImageFont.truetype(os.path.join(F, n), s)


BG, CARD = (14, 21, 38), (30, 41, 59)
WHITE, MUTED = (248, 250, 252), (148, 175, 205)
BLUE, RED, GREEN, ORANGE = (37, 99, 235), (220, 38, 38), (34, 197, 94), (245, 158, 11)

im = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(im)


def fit(text, name, size, maxw):
    while d.textlength(text, font=font(name, size)) > maxw:
        size -= 2
    return font(name, size)


title = "Safe File Organizer"
sub = "Preview · conflict check · journaled apply · one-click undo · Python, tkinter"
d.text((80, 40), title, font=fit(title, "segoeuib.ttf", 150, 1840), fill=WHITE)
d.text((80, 262), sub, font=fit(sub, "segoeui.ttf", 58, 1840), fill=MUTED)

# real screenshot: top part of the window (rules + preview with the two conflict rows), scaled to the panel
px0, py0, px1 = 80, 372, 1920
crop = Image.open(SHOT).convert("RGB").crop((0, 0, 1920, 662))
inner_w = px1 - px0 - 16
crop = crop.resize((inner_w, round(crop.height * inner_w / crop.width)), Image.LANCZOS)
py1 = py0 + crop.height + 16
d.rounded_rectangle((px0, py0, px1, py1), 28, fill=WHITE, outline=(51, 65, 85), width=4)
mask = Image.new("L", crop.size, 0)
ImageDraw.Draw(mask).rounded_rectangle((0, 0, crop.width - 1, crop.height - 1), 22, fill=255)
im.paste(crop, (px0 + 8, py0 + 8), mask)

# three number cards
cards = [("36", "files previewed, then moved", BLUE),
         ("2", "conflicting files blocked", RED),
         ("36 / 36", "restored by undo, same SHA-256", GREEN)]
cy0, cy1, gap = py1 + 50, py1 + 50 + 190, 36
cw = (1840 - 2 * gap) // 3
for i, (num, label, col) in enumerate(cards):
    x0 = 80 + i * (cw + gap)
    d.rounded_rectangle((x0, cy0, x0 + cw, cy1), 26, fill=col)
    d.rounded_rectangle((x0 + 10, cy0, x0 + cw, cy1), 26, fill=CARD)
    d.text((x0 + 45, cy0 + 12), num, font=font("segoeuib.ttf", 96), fill=WHITE)
    d.text((x0 + 45, cy0 + 122), label, font=fit(label, "segoeui.ttf", 44, cw - 70), fill=MUTED)

# badge, bottom right, same wording as the csv cover
badge = "Personal demo · Synthetic data"
bf = font("segoeuib.ttf", 52)
bw = int(d.textlength(badge, font=bf))
bx1, by1 = 1920, H - 60
bx0, by0 = bx1 - bw - 70, by1 - 90
d.rounded_rectangle((bx0, by0, bx1, by1), 18, outline=ORANGE, width=4)
d.text((bx0 + 35, by0 + 10), badge, font=bf, fill=ORANGE)
foot = "159 automated tests · real-window run, 15 of 15 disk and journal checks"
d.text((80, by0 + 22), foot, font=fit(foot, "segoeui.ttf", 38, bx0 - 120), fill=MUTED)

assert by0 > cy1 + 20, "layout overflow"
im.save(OUT)
print(OUT, im.size, os.path.getsize(OUT))
