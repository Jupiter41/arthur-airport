"""Edit timestamped browser captures into the captioned application demo.

Usage: python build_demo.py /path/to/captures
Each scene has a JSON manifest containing duration and timestamped JPEG frames.
The six selected scenes exclude navigation and loading. Time within each scene
stays at the recorded speed. Pillow crops only the injection and cascade views
for readability. FFmpeg burns captions into a band below the application.
"""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
SCENES = [
    ("01-flight-board", "01 / AIRPORT OPERATIONS", None, [
        "A synthetic airport day: 420 flights, with operations updating live.",
        "The simulation clock drives flight states and runway throughput.",
    ]),
    ("02-ground-operations", "02 / PHYSICAL CONTEXT", None, [
        "L1 adds physical context: gates, runways and ground vehicles.",
        "The ground view brings aircraft and vehicle activity together.",
    ]),
    ("03-injection-preview", "03 / DISRUPTION INJECTION", (480, 225, 1440, 675), [
        "We inject a critical runway incursion on runway 09L.",
    ]),
    ("04-cascade", "04 / CASCADE ANALYSIS", (640, 155, 1920, 755), [
        "The runway incursion triggers a closure and an arrival holding stack.",
        "The cascade then stops departures and congests gates.",
    ]),
    ("05-financial-impact", "05 / FINANCIAL IMPACT", None, [
        "L3 connects operational events to costs, revenue and P&L.",
        "The injected runway incident adds EUR 25,000 in direct costs.",
    ]),
    ("06-recommendations", "06 / DECISION SUPPORT", None, [
        "Recommendations estimate the cost and savings of possible responses.",
    ]),
]


def stamp(seconds: float, *, srt: bool = False) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    if srt:
        return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"
    return f"{hours}:{minutes:02}:{seconds:02}.{milliseconds // 10:02}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", type=Path)
    args = parser.parse_args()
    captions = []
    events = []
    timeline = []
    elapsed = 0.0
    with tempfile.TemporaryDirectory(prefix="evsk-video-") as temporary:
        build = Path(temporary)
        entries = ["ffconcat version 1.0"]
        frame_number = 0
        for name, chapter, crop, texts in SCENES:
            manifest = json.loads((args.captures / f"{name}.json").read_text())
            duration = manifest["duration"] / 1000
            timeline.append({"scene": name, "start": elapsed, "duration": duration,
                             "captured_frames": len(manifest["frames"]), "crop": crop})
            events.append(f"Dialogue: 0,{stamp(elapsed)},{stamp(elapsed + duration)},Chapter,,0,0,0,,{chapter}")
            for index, text in enumerate(texts):
                start = elapsed + index * duration / len(texts)
                end = elapsed + (index + 1) * duration / len(texts)
                captions.append((start, end, text))
                events.append(f"Dialogue: 1,{stamp(start)},{stamp(end)},Subtitle,,0,0,0,,{text}")
            frames = manifest["frames"]
            for index, frame in enumerate(frames):
                destination = build / f"frame-{frame_number:05}.jpg"
                with Image.open(frame["file"]) as image:
                    assert image.size == (1920, 900), "Recording viewport changed"
                    if crop:
                        image = image.crop(crop).resize((1920, 900), Image.Resampling.LANCZOS)
                        image.save(destination, quality=95)
                    else:
                        destination.symlink_to(Path(frame["file"]).resolve())
                next_time = frames[index + 1]["time"] if index + 1 < len(frames) else manifest["duration"]
                entries.extend([f"file '{destination}'", f"duration {(next_time - frame['time']) / 1000:.6f}"])
                frame_number += 1
            elapsed += duration
        entries.append(f"file '{destination}'")
        (build / "frames.txt").write_text("\n".join(entries) + "\n")

        ass = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Chapter,Lato,23,&H00D4E1F2,&H00FFFFFF,&H00101A27,&H00101A27,-1,0,0,0,100,100,1.5,0,1,0,0,7,44,44,926,1
Style: Subtitle,Lato,34,&H00FFFFFF,&H00FFFFFF,&H00101A27,&H00101A27,0,0,0,0,100,100,0,0,1,0,0,2,70,70,55,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(events)
        (ROOT / "demo.ass").write_text(ass + "\n")
        srt = "\n\n".join(
            f"{index}\n{stamp(start, srt=True)} --> {stamp(end, srt=True)}\n{text}"
            for index, (start, end, text) in enumerate(captions, 1)
        )
        (ROOT / "demo.srt").write_text(srt + "\n")
        (ROOT / "demo-edit.json").write_text(json.dumps({
            "duration_seconds": elapsed, "viewport": [1920, 900],
            "output": [1920, 1080], "audio": "silent", "scenes": timeline,
        }, indent=2) + "\n")
        subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
            "-f", "concat", "-safe", "0", "-i", str(build / "frames.txt"),
            "-vf", f"pad=1920:1080:0:0:color=0x101a27,subtitles={ROOT / 'demo.ass'},fps=25",
            "-t", f"{elapsed:.3f}", "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(ROOT / "demo.mp4"),
        ], check=True)

    # Use a genuine frame from the physical airport scene for the PDF's play link.
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "10",
        "-i", str(ROOT / "demo.mp4"), "-frames:v", "1", str(ROOT / "demo-poster.png"),
    ], check=True)
    with Image.open(ROOT / "demo-poster.png") as image:
        draw = ImageDraw.Draw(image, "RGBA")
        draw.rounded_rectangle((760, 330, 1160, 550), radius=30, fill=(15, 26, 39, 225),
                               outline=(212, 225, 242, 180), width=2)
        draw.polygon([(930, 370), (930, 455), (1000, 412)], fill=(255, 255, 255, 255))
        font_path = subprocess.check_output(["fc-match", "-f", "%{file}", "Lato"], text=True)
        font = ImageFont.truetype(font_path, 28)
        draw.text((960, 500), f"Play demo · {round(elapsed)} seconds", font=font,
                  fill="white", anchor="mm")
        image.save(ROOT / "demo-poster.png")
    print(f"Edited {frame_number} captured frames into {elapsed:.2f} seconds")


if __name__ == "__main__":
    main()
