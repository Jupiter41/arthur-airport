"""Build a portable browser deck with the recorded demo embedded on page 13.

Run after compiling slides.typ to slides.pdf and producing demo.mp4.
Requires Poppler (pdftoppm), Pillow and pypdf.
"""

import base64
import html
import io
import json
from pathlib import Path
import subprocess
import tempfile

from PIL import Image
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parent


def data_url(path: Path, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def main() -> None:
    reader = PdfReader(ROOT / "slides.pdf")
    slides = []
    with tempfile.TemporaryDirectory(prefix="evsk-deck-") as temporary:
        prefix = Path(temporary) / "slide"
        subprocess.run(
            ["pdftoppm", "-scale-to", "1600", "-png", str(ROOT / "slides.pdf"), str(prefix)],
            check=True,
        )
        renders = sorted(Path(temporary).glob("slide-*.png"))
        assert len(renders) == len(reader.pages) == 20, "Expected the original 20 pages"
        for number, path in enumerate(renders, 1):
            output = io.BytesIO()
            with Image.open(path) as image:
                image.convert("RGB").save(output, "WEBP", quality=92, method=6)
            image_url = "data:image/webp;base64," + base64.b64encode(output.getvalue()).decode()
            text = reader.pages[number - 1].extract_text()
            label = html.escape(f"Slide {number}: {text[:180]}", quote=True)
            slides.append(
                f'<section class="slide" aria-label="Slide {number}" hidden>'
                f'<img src="{image_url}" alt="{label}" draggable="false"></section>'
            )

    template = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>EVSK · Progressive fidelity</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#101a27;color:white;font:15px system-ui}
main{height:100dvh;display:grid;place-items:center;padding:0 0 40px}
#stage{position:relative;width:min(100vw,calc((100dvh - 40px)*16/9));aspect-ratio:16/9;background:white}
.slide{position:absolute;inset:0}.slide img{width:100%;height:100%;object-fit:contain}
[hidden]{display:none!important}
#demo{position:absolute;left:4.6875%;top:22.2222%;width:90.625%;height:66.6667%;object-fit:contain;background:#101a27;border-radius:8px}
nav{position:fixed;bottom:0;left:0;right:0;height:40px;display:flex;align-items:center;justify-content:center;gap:18px;background:#101a27}
button{font:inherit;color:#d4e1f2;border:0;background:transparent;cursor:pointer;padding:6px 12px;border-radius:4px}
button:hover,button:focus-visible{background:#294363}button:disabled{opacity:.3;cursor:default}
#count{min-width:55px;text-align:center;font-variant-numeric:tabular-nums}
.hint{position:absolute;right:20px;color:#8fa7c6;font-size:12px}
@media(max-width:760px){.hint{display:none}}
@media print{main{display:block;height:auto;padding:0}#stage{width:100%}.slide{position:relative;display:block!important;break-after:page}#demo,nav{display:none}}
</style></head><body>
<main><div id="stage" aria-live="polite">__SLIDES__
<video id="demo" aria-label="Captioned airport application demonstration" controls muted playsinline preload="metadata" poster="__POSTER__" hidden>
<source src="__VIDEO__" type="video/mp4">Your browser cannot play this video. Open demo.mp4 instead.
</video></div></main>
<nav aria-label="Slide navigation"><button id="previous" aria-label="Previous slide">←</button>
<span id="count" aria-live="polite"></span><button id="next" aria-label="Next slide">→</button>
<button id="fullscreen" aria-label="Toggle fullscreen">Fullscreen</button>
<span class="hint">← → slides · Space play / pause · F fullscreen</span></nav>
<script>
const slides=[...document.querySelectorAll('.slide')], video=document.querySelector('#demo');
let current=0;
function show(index){
  index=Math.max(0,Math.min(slides.length-1,index));
  if(index!==12)video.pause();
  current=index;slides.forEach((slide,i)=>slide.hidden=i!==index);
  video.hidden=index!==12;
  document.querySelector('#count').textContent=`${index+1} / ${slides.length}`;
  document.querySelector('#previous').disabled=index===0;
  document.querySelector('#next').disabled=index===slides.length-1;
  history.replaceState(null,'',`#${index+1}`);
  if(index===12)video.play().catch(()=>{});
}
function fullscreen(){if(document.fullscreenElement)document.exitFullscreen();else document.documentElement.requestFullscreen().catch(()=>{});}
document.querySelector('#previous').onclick=()=>show(current-1);
document.querySelector('#next').onclick=()=>show(current+1);
document.querySelector('#fullscreen').onclick=fullscreen;
document.addEventListener('keydown',event=>{
  if(event.target instanceof HTMLButtonElement && [' ','Enter'].includes(event.key))return;
  if(['ArrowRight','PageDown'].includes(event.key)){event.preventDefault();show(current+1)}
  else if(['ArrowLeft','PageUp'].includes(event.key)){event.preventDefault();show(current-1)}
  else if(event.key==='Home'){event.preventDefault();show(0)}
  else if(event.key==='End'){event.preventDefault();show(slides.length-1)}
  else if(event.key.toLowerCase()==='f')fullscreen();
  else if(event.key===' '){event.preventDefault();if(current===12){if(video.paused)video.play().catch(()=>{});else video.pause()}else show(current+1)}
});
function openHash(){const number=Number(location.hash.slice(1));show(Number.isFinite(number)&&number>0?Math.trunc(number)-1:0);}
window.addEventListener('hashchange',openHash);openHash();
</script></body></html>"""
    output = template.replace("__SLIDES__", "\n".join(slides))
    output = output.replace("__POSTER__", data_url(ROOT / "demo-poster.png", "image/png"))
    output = output.replace("__VIDEO__", data_url(ROOT / "demo.mp4", "video/mp4"))
    (ROOT / "slides.html").write_text(output)
    print(json.dumps({"slides": len(slides), "output": str(ROOT / "slides.html")}))


if __name__ == "__main__":
    main()
