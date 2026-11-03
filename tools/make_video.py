"""Cut the portfolio video from the unedited raw screen recording and burn in English captions.

Only real frames of the recorded run are used (trim + captions; no speed change, no inserted frames).
Captions are rendered with PIL into transparent PNGs and overlaid with ffmpeg (this ffmpeg build has no
drawtext/subtitles filter). Caption times are raw-recording seconds, read from where the recorded run's
screen changes (ffmpeg scene detection) and matched to the steps in tools/a27_ui_run.py.
"""
import os, subprocess, sys, tempfile
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(ROOT, "video", "raw", "safe-file-organizer-real-run.mp4")
OUT = os.path.join(ROOT, "video", "out", "safe-file-organizer-demo.mp4")
START, END = 1.0, 60.8   # raw seconds kept
CAPS = [  # (raw start, raw end, text)
    (1.2, 4.9, "Safe File Organizer: a real desktop app, run on synthetic demo files"),
    (5.0, 11.6, "Step 1: choose the conflict-test folder with the native folder picker"),
    (11.8, 16.6, "Rules: sort into Organized\\ by extension, include sub folders"),
    (16.7, 22.1, "Conflict interception: two invoice.pdf files map to one target, so Apply is disabled"),
    (22.3, 28.8, "Step 2: choose the 36-file demo folder (nothing was changed in the conflict folder)"),
    (28.9, 33.5, "Rules: prefix Doc_, add a number, sort by extension"),
    (33.6, 39.6, "Preview: 36 ready, 0 conflicts. No file has moved yet"),
    (39.7, 43.3, "Apply asks for confirmation first"),
    (43.4, 49.8, "Apply: 36 files moved and renamed, and the run is written to a journal"),
    (49.9, 53.4, "Undo also asks for confirmation"),
    (53.5, 60.8, "Undo: all 36 files are back at their original paths, same SHA-256"),
]
FONT = ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf", 40)


def caption_png(text, path):
    im = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    w = d.textlength(text, font=FONT)
    x0, y0 = (1920 - w) / 2, 940
    d.rounded_rectangle((x0 - 28, y0 - 14, x0 + w + 28, y0 + 66), 14, fill=(10, 16, 28, 215))
    d.text((x0, y0), text, font=FONT, fill=(255, 255, 255, 255))
    im.save(path)


def main():
    tmp = tempfile.mkdtemp()
    cmd = ["ffmpeg", "-hide_banner", "-y", "-i", RAW]
    for n, (_a, _b, t) in enumerate(CAPS):
        p = os.path.join(tmp, f"c{n}.png")
        caption_png(t, p)
        cmd += ["-loop", "1", "-framerate", "30", "-i", p]
    chain = f"[0:v]trim=start={START}:end={END},setpts=PTS-STARTPTS[v0]"
    prev = "v0"
    for n, (a, b, _t) in enumerate(CAPS):
        chain += f";[{prev}][{n+1}:v]overlay=0:0:enable='between(t,{a-START:.2f},{b-START:.2f})':shortest=0[v{n+1}]"
        prev = f"v{n+1}"
    cmd += ["-filter_complex", chain, "-map", f"[{prev}]", "-an", "-c:v", "libx264", "-preset", "slow",
            "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30", "-movflags", "+faststart", "-t",
            f"{END-START:.2f}", OUT]
    subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL)
    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)


if __name__ == "__main__":
    main()
