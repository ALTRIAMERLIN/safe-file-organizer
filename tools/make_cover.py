"""Build deliverables/cover.png (2000x1500, 4:3) with PIL. Text and shapes only: no screenshot, no fake UI."""
import os
from PIL import Image, ImageDraw, ImageFont

W, H = 2000, 1500
F = r"C:\Windows\Fonts"
def font(n, s): return ImageFont.truetype(os.path.join(F, n), s)

im = Image.new("RGB", (W, H))
px = ImageDraw.Draw(im)
for y in range(H):  # vertical gradient
    t = y / H
    px.line([(0, y), (W, y)], fill=(int(16 + 10 * t), int(24 + 14 * t), int(42 + 22 * t)))
d = ImageDraw.Draw(im)
ACC, WHITE, MUTED = (74, 163, 255), (255, 255, 255), (168, 182, 205)

def fit(text, name, size, maxw):
    while d.textlength(text, font=font(name, size)) > maxw:
        size -= 2
    return font(name, size)

d.rectangle((0, 0, 24, H), fill=ACC)
d.text((140, 150), "PYTHON DESKTOP TOOL  ·  WINDOWS", font=font("segoeuib.ttf", 40), fill=ACC)
d.text((140, 240), "Safe File Organizer", font=fit("Safe File Organizer", "segoeuib.ttf", 170, 1720), fill=WHITE)
d.text((140, 450), "Preview every move. Apply. Undo it all.", font=fit("Preview every move. Apply. Undo it all.", "segoeui.ttf", 76, 1720), fill=MUTED)

points = [("Preview first", "Every rename and move is listed before anything changes"),
          ("Conflicts blocked", "Two files with the same target stop the whole run"),
          ("Journaled apply", "Each move is logged before and after, no overwrite"),
          ("One-click undo", "36 of 36 files restored, SHA-256 identical")]
y = 660
for head, sub in points:
    d.rounded_rectangle((140, y, 1860, y + 150), 22, fill=(27, 40, 66), outline=(48, 70, 110), width=3)
    d.ellipse((180, y + 50, 230, y + 100), fill=ACC)
    d.text((270, y + 18), head, font=font("segoeuib.ttf", 58), fill=WHITE)
    d.text((270, y + 88), sub, font=fit(sub, "segoeui.ttf", 40, 1540), fill=MUTED)
    y += 180

d.text((140, 1420), "Personal demo project  ·  synthetic data only  ·  159 automated tests",
       font=fit("Personal demo project  ·  synthetic data only  ·  159 automated tests", "segoeui.ttf", 40, 1720), fill=MUTED)
im.save(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deliverables", "cover.png"))
