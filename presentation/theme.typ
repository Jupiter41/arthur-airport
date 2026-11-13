// EVSK paper, workshop talk theme.
// Built on touying 0.7.4 core (a true 1280x720pt 16:9 canvas).
// Design goals: one idea per slide, big type, generous whitespace,
// a per-layer accent system, hero statements, stat tiles and figure slides.
#import "@preview/touying:0.7.4": *

// ---------------------------------------------------------------------------
// Palette
// ---------------------------------------------------------------------------
#let ink        = rgb("#16202e")   // body text
#let navy       = rgb("#1b3a5b")   // brand / primary (deep sky blue)
#let air-blue   = rgb("#1b3a5b")
#let blue-light = rgb("#3f7ab0")
#let green      = rgb("#2f6f4f")
#let amber      = rgb("#b8741a")
#let gray       = rgb("#5f6b7a")
#let hair       = rgb("#d9e0ea")
#let card       = rgb("#eff3f8")
#let cream      = rgb("#f7efe1")
#let paper      = rgb("#ffffff")
#let on-navy    = rgb("#d4e1f2")   // light text on navy
#let on-navy-dim = rgb("#8fa7c6")

// Layer colours: one per capability layer, used consistently everywhere.
#let layer-color = (
  "L0": rgb("#52657d"),
  "L1": rgb("#3f7ab0"),
  "L2": rgb("#2f6f4f"),
  "L3": rgb("#b8741a"),
)

// ---------------------------------------------------------------------------
// Small atoms
// ---------------------------------------------------------------------------

// Eyebrow / kicker label above a slide title.
#let kicker(body, fill: blue-light) = text(
  size: 0.52em, weight: "bold", fill: fill, tracking: 0.12em,
)[#upper(body)]

// Pill badge: layer marker (L0..L3) or research-question tag.
#let pill(label, fill) = box(
  inset: (x: 0.6em, y: 0.26em),
  radius: 1em,
  fill: fill,
  text(size: 0.42em, weight: "bold", fill: white, tracking: 0.04em, label),
)
#let layer-tag(name) = pill(name, layer-color.at(name, default: blue-light))
#let rq1 = pill("RQ1", navy)
#let rq2 = pill("RQ2", navy)
#let finding = pill("FINDING", green)
#let gap = pill("GAP", amber)

// Inline callout box (note / gap / principle).
#let callout(body, accent: amber, fill: cream) = block(
  width: 100%,
  inset: (x: 1em, y: 0.85em),
  radius: 0.35em,
  fill: fill,
  stroke: (left: 4pt + accent, rest: 0pt),
)[#body]

// Clean bulleted list (bigger default spacing, custom marker).
// Body uses `-` item syntax; we restyle the markers via a set rule.
#let air-list(spacing: 0.75em, marker: text(blue-light)[▪], body) = {
  set list(marker: marker, spacing: spacing, body-indent: 0.6em)
  body
}

// Two (or more) equal columns with a gutter.
#let cols(..children) = {
  let bodies = children.pos()
  let gutter = children.named().at("gutter", default: 1.4em)
  grid(columns: (1fr,) * bodies.len(), column-gutter: gutter, ..bodies)
}

// A soft card used for the fidelity dimensions and similar panels.
#let card-panel(body, accent: blue-light, height: auto) = block(
  width: 100%,
  height: height,
  inset: 1em,
  radius: 0.4em,
  fill: card,
  stroke: (top: 3pt + accent, rest: 0.75pt + hair),
)[#body]

// Big number stat tile.
#let stat(value, label, accent: navy) = block(
  width: 100%,
  inset: (x: 0.6em, y: 0.9em),
  radius: 0.4em,
  fill: card,
  stroke: (bottom: 3pt + accent, rest: 0.75pt + hair),
)[
  #align(center)[
    #text(size: 1.5em, weight: "black", fill: accent)[#value]
    #v(0.2em)
    #text(size: 0.5em, fill: gray, tracking: 0.04em)[#upper(label)]
  ]
]

// Step chip used in the "twins grow" pipeline.
#let step-chip(label, accent) = box(
  inset: (x: 1em, y: 0.7em),
  radius: 0.4em,
  fill: accent.lighten(84%),
  stroke: 1.2pt + accent,
  text(size: 0.9em, weight: "bold", fill: accent.darken(12%))[#label],
)
#let arrow = text(size: 1.1em, fill: gray)[➜]

// Small neutral chip (used for the spec / guardrail inventories).
#let chip(body, accent: gray) = box(
  inset: (x: 0.6em, y: 0.34em),
  radius: 0.3em,
  fill: card,
  stroke: (left: 2.5pt + accent, rest: 0.75pt + hair),
  text(size: 0.62em, fill: ink)[#body],
)

// Horizontal bar (used by the blast-radius chart). `frac` in [0,1].
#let hbar(label, frac, accent, annot) = grid(
  columns: (5em, 1fr, 9.5em),
  column-gutter: 0.8em,
  align: (right + horizon, left + horizon, left + horizon),
  text(size: 0.7em, weight: "bold")[#label],
  box(width: 100%, height: 1.5em, fill: card, radius: 0.2em)[
    #place(left + horizon,
      rect(width: frac * 100%, height: 1.5em, radius: 0.2em, fill: accent))
  ],
  text(size: 0.62em, fill: gray)[#annot],
)

// ---------------------------------------------------------------------------
// Slide title block (eyebrow + title + thin accent rule + optional tag).
// ---------------------------------------------------------------------------
#let slide-heading(title, eyebrow: none, tag: none, accent: navy) = {
  block(below: 0.7em, width: 100%)[
    #if eyebrow != none [#kicker(eyebrow)#v(0.25em)]
    #grid(
      columns: (1fr, auto),
      align: (left + bottom, right + bottom),
      text(size: 1.15em, weight: "bold", fill: navy)[#title],
      if tag != none { if type(tag) == function { tag() } else { tag } },
    )
    #v(0.3em)
    #line(length: 100%, stroke: 0.9pt + hair)
  ]
}

// ---------------------------------------------------------------------------
// Chrome: a slim footer (brand left, counter right). No heavy header band.
// ---------------------------------------------------------------------------
#let air-slide(
  config: (:),
  repeat: auto,
  setting: body => body,
  composer: auto,
  ..bodies,
) = touying-slide-wrapper(self => {
  let footer(self) = {
    set text(size: 0.5em, fill: gray)
    components.left-and-right(
      utils.call-or-display(self, self.store.footer),
      utils.call-or-display(self, self.store.footer-right),
    )
  }
  let self = utils.merge-dicts(self, config-page(footer: footer))
  touying-slide(
    self: self, config: config, repeat: repeat,
    setting: setting, composer: composer, ..bodies,
  )
})

// ---------------------------------------------------------------------------
// The theme
// ---------------------------------------------------------------------------
#let air-theme(
  title: "A Layered Architecture for Digital Twins with Progressive Fidelity",
  subtitle: "A case study in airport operations with specification-first development",
  author: "Arthur Chevallier & German Castignani",
  date: "2026",
  footer-brand: [EVSK · progressive fidelity],
  body,
) = {
  show: touying-slides.with(
    config-page(
      width: 1280pt,
      height: 720pt,
      margin: (top: 40pt, right: 60pt, bottom: 40pt, left: 60pt),
      fill: paper,
    ),
    config-common(
      slide-fn: air-slide,
      breakable: false,
      zero-margin-footer: false,
    ),
    config-methods(
      init: (self: none, body) => {
        set text(font: "Lato", size: 25pt, fill: ink)
        set par(leading: 0.72em, spacing: 0.9em)
        show raw: set text(font: "Ubuntu Mono", size: 0.86em)
        set list(marker: text(blue-light)[▪])
        body
      },
      alert: utils.alert-with-primary-color,
    ),
    config-colors(
      primary: navy,
      neutral-light: gray,
      neutral-lightest: white,
      neutral-darkest: ink,
    ),
    config-store(
      footer: footer-brand,
      footer-right: context utils.slide-counter.display()
        + " / " + utils.last-slide-number,
    ),
    config-info(title: title, subtitle: subtitle, author: author, date: date),
  )
  body
}

// ---------------------------------------------------------------------------
// Full-bleed title slide.
// ---------------------------------------------------------------------------
#let air-title-slide(
  title, subtitle: none, authors: none, affiliation: none,
  venue: none, footer-note: none,
) = slide(
  config: utils.merge-dicts(
    config-page(fill: navy, header: none, footer: none,
      margin: (x: 80pt, y: 60pt)),
    config-common(freeze-slide-counter: true),
  ),
)[
  #set text(fill: white)
  // layer accent strip
  #place(top + left, dx: -80pt, dy: -60pt,
    stack(dir: ltr,
      ..("L0","L1","L2","L3").map(k =>
        rect(width: 320pt, height: 8pt, fill: layer-color.at(k)))))
  #align(left + horizon)[
    #kicker("Digital twins · progressive fidelity", fill: on-navy-dim)
    #v(0.6em)
    #text(size: 1.7em, weight: "black")[#title]
    #v(0.5em)
    #if subtitle != none [#text(size: 0.95em, fill: on-navy)[#subtitle]]
    #v(1.6em)
    #if authors != none [#text(size: 0.85em, weight: "bold")[#authors]]
    #v(0.25em)
    #if affiliation != none [#text(size: 0.68em, fill: on-navy)[#affiliation]]
    #v(0.5em)
    #if venue != none [
      #box(inset: (x: 0.7em, y: 0.35em), radius: 0.3em,
        fill: white.transparentize(88%), stroke: 1pt + on-navy-dim)[
        #text(size: 0.6em, weight: "bold", fill: on-navy)[#venue]]
    ]
  ]
  #place(bottom + left,
    text(size: 0.5em, fill: on-navy-dim)[#footer-note])
]

// ---------------------------------------------------------------------------
// Section-divider slide: big act number + section title on navy.
// ---------------------------------------------------------------------------
#let air-divider-slide(number, heading, note: none) = slide(
  config: utils.merge-dicts(
    config-page(fill: navy, header: none, footer: none,
      margin: (x: 80pt, y: 60pt)),
    config-common(freeze-slide-counter: true),
  ),
)[
  #set text(fill: white)
  #align(left + horizon)[
    #text(size: 3.4em, weight: "black", fill: on-navy-dim.transparentize(20%))[#number]
    #v(0.1em)
    #text(size: 1.6em, weight: "bold")[#heading]
    #if note != none [
      #v(0.5em)
      #text(size: 0.8em, fill: on-navy)[#note]
    ]
  ]
]

// ---------------------------------------------------------------------------
// Hero statement slide: one big sentence, the "one idea". Cream background.
// ---------------------------------------------------------------------------
#let air-hero-slide(statement, eyebrow: none, sub: none, accent: green) = slide(
  config: utils.merge-dicts(
    config-page(fill: cream, header: none, footer: none,
      margin: (x: 90pt, y: 70pt)),
    config-common(freeze-slide-counter: false),
  ),
)[
  #place(left + horizon, dx: -90pt,
    rect(width: 10pt, height: 70%, fill: accent))
  #align(left + horizon)[
    #if eyebrow != none [#kicker(eyebrow, fill: accent.darken(10%))#v(0.6em)]
    #text(size: 1.55em, weight: "bold", fill: ink)[#statement]
    #if sub != none [
      #v(0.7em)
      #text(size: 0.82em, fill: gray)[#sub]
    ]
  ]
]

// Closing slide (Thank you / Q&A).
#let air-closing-slide(heading, note: none) = slide(
  config: utils.merge-dicts(
    config-page(fill: navy, header: none, footer: none,
      margin: (x: 80pt, y: 60pt)),
    config-common(freeze-slide-counter: true),
  ),
)[
  #set text(fill: white)
  #place(top + left, dx: -80pt, dy: -60pt,
    stack(dir: ltr,
      ..("L0","L1","L2","L3").map(k =>
        rect(width: 320pt, height: 8pt, fill: layer-color.at(k)))))
  #align(left + horizon)[
    #text(size: 2.6em, weight: "black")[#heading]
    #if note != none [
      #v(0.8em)
      #text(size: 0.85em, fill: on-navy)[#note]
    ]
  ]
]
