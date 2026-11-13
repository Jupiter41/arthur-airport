# Workshop slides

Open `slides.html` in a browser to present the complete 20-page deck. This is a
self-contained file: the slide images and the captioned video are embedded, so
it works offline without the airport app or a local server.

Use the arrow keys to navigate, **F** for fullscreen, and **Space** to play or
pause the video on slide 13. Its native video controls also allow fullscreen
playback of the demo itself.

`slides.pdf` contains the full MP4 and an in-page video player on page 13. Click
the recording's poster in a PDF viewer with RichMedia video support, such as
desktop Adobe Acrobat/Reader. Playback is configured to stay on the page and
stop when the slide leaves view. The separate MP4 is not required. PDF viewers
without RichMedia support show the poster instead. Use `slides.html` for browser
playback. The embedded media and poster have been checked structurally and
visually. Playback in desktop Acrobat/Reader has not been tested here.

The 46-second silent recording shows actual application screens: the flight
board, ground operations, a critical runway incursion, the resulting incident
cascade, financial impact and suggested responses. English subtitles are burned
into the video. Optional live aircraft polling was disabled for this recording.
Navigation and loading are omitted. The injection and cascade scenes use closer
crops. Each selected scene plays at its captured speed.

## Editing

- Edit slide content in `slides.typ` and shared styling in `theme.typ`.
- Compile with `typst compile slides.typ slides.pdf` from this directory.
- Run `python embed_pdf_video.py` to embed the player and video in the PDF
  (pypdf required). Recompiling Typst replaces the PDF, so repeat this step after
  each compile. The embedder verifies that the embedded bytes match the MP4.
- Rebuild the portable deck with `python build_presenter.py` (Pillow, pypdf and
  Poppler required).
- `demo.srt` holds the subtitle text. `demo.ass` includes subtitle styling and
  chapter labels. `demo-edit.json` documents the cut timings and crops.
- `build_demo.py` can rebuild the video from timestamped capture manifests and
  JPEG frames. Raw capture frames are working files, separate from the deck.

The airport containers started for recording were stopped afterwards. Their
data volumes were preserved.
