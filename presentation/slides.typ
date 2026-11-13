// EVSK paper, workshop talk (approx. 15 min).
// A visual, one-idea-per-slide deck. Each slide carries a short presenter
// cue in a `// SAY:` comment: the single thing to land out loud.
#import "theme.typ": *

#show: air-theme.with(
  title: "A Layered Architecture for Digital Twins with Progressive Fidelity",
  subtitle: "A case study in airport operations with specification-first development",
  author: "Arthur Chevallier & German Castignani",
  date: "2026",
  footer-brand: [EVSK · progressive fidelity],
)

// ===========================================================================
// 1 · Title
// SAY: Twins grow; the question is how to grow them without breaking what
//      already works.
// ===========================================================================
#air-title-slide(
  [A Layered Architecture for Digital Twins\ with Progressive Fidelity],
  subtitle: [How a digital twin can grow in fidelity, without rewriting what already works.],
  authors: [Arthur Chevallier · German Castignani],
  affiliation: [Luxembourg Institute of Science and Technology],
  venue: [Workshop talk · 15 minutes],
  footer-note: [Open-source prototype · EVSK · VirtualSky International Airport],
)

// ===========================================================================
// 2 · Definition: three dimensions of fidelity
// SAY: Fidelity is how closely a twin represents the system it models.
//      Spatial detail, timing and behavioural realism can evolve separately.
// ===========================================================================
#slide[
  #slide-heading([Fidelity in a digital twin], eyebrow: "Definition")

  #v(0.35em)
  #text(size: 0.96em, fill: navy)[Fidelity describes how closely a digital twin represents the system it models.]
  #v(0.8em)
  #grid(
    columns: (1fr, 1fr, 1fr),
    column-gutter: 1.4em,
    ..(
      ("Spatial", "geometry and position", "Logical connections", "Coarse geometry", "Detailed geometry", layer-color.at("L1")),
      ("Temporal", "timing and change", "Coarse event timing", "Finer time resolution", "Subsecond updates", layer-color.at("L2")),
      ("Behavioural", "how the system responds", "State transitions", "Rules and interactions", "Data-calibrated dynamics", layer-color.at("L3")),
    ).map(d => block(
      width: 100%, height: 10.7em, inset: 1em, radius: 0.5em,
      fill: d.at(5).lighten(90%),
      stroke: (top: 4pt + d.at(5), rest: 0.75pt + d.at(5).lighten(40%)),
    )[
      #align(center)[
        #text(size: 1.15em, weight: "bold", fill: d.at(5).darken(12%))[#d.at(0)]
        #v(0.1em)
        #text(size: 0.66em, fill: gray, style: "italic")[#d.at(1)]
        #v(0.65em)
        #stack(dir: ttb, spacing: 0.4em,
          text(size: 0.84em)[#d.at(2)],
          text(size: 0.78em, fill: d.at(5))[↓],
          text(size: 0.84em)[#d.at(3)],
          text(size: 0.78em, fill: d.at(5))[↓],
          text(size: 0.9em, weight: "bold", fill: d.at(5).darken(12%))[#d.at(4)],
        )
      ]
    ]),
  )
  #v(1.1em)
  #callout(accent: green, fill: cream)[
    #text(size: 0.84em)[
      *Fidelity depends on the purpose.* A twin can be detailed in one dimension
      and simplified in another.
    ]
  ]
]

// ===========================================================================
// 3 · Hook: twins grow
// SAY: Nobody builds a twin at full resolution on day one. It grows in
//      stages. Changing entity IDs, feed conventions or the event write path
//      can break earlier capabilities and invalidate previous experiments.
// ===========================================================================
#slide[
  #slide-heading(
    [Digital twins are not born complete, they grow],
    eyebrow: "The problem",
  )

  #v(0.55em)
  #text(size: 0.92em, fill: gray)[When contracts change, a fidelity upgrade can break what already works.]
  #v(0.9em)

  #let stage(label, accent) = box(
    width: 215pt, height: 66pt, radius: 0.4em,
    fill: accent.lighten(84%), stroke: 1.2pt + accent,
  )[#align(center + horizon)[#text(size: 0.9em, weight: "bold", fill: accent.darken(12%))[#label]]]
  #grid(columns: (215pt, 100pt, 215pt, 100pt, 215pt, 100pt, 215pt),
    align: center + horizon,
    stage([Logical model], layer-color.at("L0")), arrow,
    stage([Physical layout], layer-color.at("L1")), arrow,
    stage([Live data], layer-color.at("L2")), arrow,
    stage([Decisions], layer-color.at("L3")),
  )
  // Each example is centered directly beneath its transition arrow.
  #grid(columns: (215pt, 100pt, 215pt, 100pt, 215pt, 100pt, 215pt),
    align: center,
    [], line(angle: 90deg, length: 32pt, stroke: 1.2pt + hair),
    [], line(angle: 90deg, length: 32pt, stroke: 1.2pt + hair),
    [], line(angle: 90deg, length: 32pt, stroke: 1.2pt + hair), [],
  )
  #v(0.45em)
  #let example(title, body) = [
    #text(size: 0.86em, weight: "bold", fill: amber)[#title]
    #v(0.4em)
    #text(size: 0.82em, fill: gray)[#body]
  ]
  #grid(columns: (115pt, 300pt, 15pt, 300pt, 15pt, 300pt, 115pt),
    [],
    example([Entity IDs disappear], [
      A geometry upgrade replaces entity IDs with coordinates. Existing lookup logic loses its inputs.
    ]), [],
    example([Live feeds disagree], [
      A feed uses different entity IDs or timestamp conventions. Objects duplicate and state estimates drift.
    ]), [],
    example([Decisions bypass events], [
      An optimiser changes state without emitting events. The audit trail and replay no longer match.
    ]), [],
  )

  #v(1.1em)
  #callout(accent: amber)[
    #text(size: 0.84em)[
      *The cost spreads beyond the new layer:* consumer rewrites, repeated validation,
      and past experiments that may no longer be reproducible.
    ]
  ]
]

// ===========================================================================
// 4 · The gap + RQ1
// SAY: Existing frameworks tell you how to *slice* a twin into layers. None
//      govern how fidelity is allowed to *grow* across those slices.
// ===========================================================================
#slide[
  #slide-heading([The gap in existing frameworks], eyebrow: "Why this work")

  #v(0.8em)
  #cols(gutter: 2em)[
    #text(weight: "bold", fill: navy)[What they give us]
    #air-list(spacing: 0.55em)[
      - ISO 23247: manufacturing reference architecture
      - Tao et al.: physical / virtual / data / services / connections
      - Redelinghuys et al.: acquisition to emulation
    ]
    #v(0.3em)
    #text(size: 0.78em, fill: gray)[Good decompositions of *what a twin is made of.*]
  ][
    #text(weight: "bold", fill: amber)[What they leave open]
    #v(0.3em)
    #text(size: 0.9em)[
      None make *fidelity-preserving evolution* an explicit constraint.
      Higher fidelity should *extend* a lower layer, not restructure it.
    ]
  ]

  #v(1.2em)
  #callout(accent: navy, fill: card)[
    #text(size: 0.9em)[
      #text(weight: "bold", fill: navy)[RQ1] #h(0.5em) How can a digital-twin
      architecture support progressive increases in fidelity *while preserving
      the contracts and functionality of previously implemented layers?*
    ]
  ]
]

// ===========================================================================
// 5 · HERO: the one idea
// SAY: This is the whole paper in one line. Fidelity goes up by *extending a
//      contract*. You may add to C_i; you may never modify or remove C_j.
// ===========================================================================
#air-hero-slide(
  [Raise fidelity by *extending* a layer's contract,\ never by rewriting it.],
  eyebrow: "The core idea",
  sub: [
    Each layer $L_i$ exposes a contract $C_i$. Upgrading may *extend* $C_i$,
    but must not modify or remove any existing element of any $C_j$.
    Append-only contracts: the layers above keep running, untouched.
  ],
  accent: green,
)

// ===========================================================================
// 6 · EVSK: the case study (introduced before the architecture deep-dive)
// SAY: Before we show the architecture, let me introduce the instrument we
//      used to build and study it. EVSK is a fully open-source airport
//      digital twin. The airport is our testbed, not our subject.
// ===========================================================================
#slide[
  #slide-heading([EVSK · VirtualSky International Airport], eyebrow: "The case study")

  #v(0.5em)
  #text(size: 1.04em, fill: navy)[An open-source airport twin for studying how fidelity grows.]
  #v(1em)

  #grid(columns: (0.95fr, 1.15fr), column-gutter: 2.5em,
    [
      #text(weight: "bold", fill: navy)[Why an airport?]
      #v(0.45em)
      #text(size: 0.87em)[Flights, passengers, baggage and weather interact across different timescales.]
      #v(0.7em)
      #text(size: 0.87em)[Established delay, cost and flow models let us focus on *the architecture and its boundaries*.]
      #v(0.7em)
      #text(size: 0.76em, fill: gray)[Synthetic operations. Optional live feeds at L2. Open-source and DOI-archived.]
    ],
    [
      #text(weight: "bold", fill: navy)[Four implemented layers]
      #v(0.55em)
      #grid(columns: (auto, 1fr), column-gutter: 0.75em,
        row-gutter: 0.8em, align: (left + horizon, left + horizon),
        layer-tag("L0"), [#text(size: 0.84em)[*Logical core*] #linebreak() #text(size: 0.68em, fill: gray)[Domain services, Kafka events and Neo4j]],
        layer-tag("L1"), [#text(size: 0.84em)[*Physical layout*] #linebreak() #text(size: 0.68em, fill: gray)[Gates, routes and travel times]],
        layer-tag("L2"), [#text(size: 0.84em)[*Observed data*] #linebreak() #text(size: 0.68em, fill: gray)[Geospatial context and switchable feeds]],
        layer-tag("L3"), [#text(size: 0.84em)[*Decision support*] #linebreak() #text(size: 0.68em, fill: gray)[Analysis, costs and gated recommendations]],
      )
    ],
  )
]

// ===========================================================================
// Divider ① : the architecture
// ===========================================================================
#air-divider-slide([01], [A four-layer fidelity architecture],
  note: [Explicit contracts · append-only evolution · a decisional layer that closes the loop.])

// ===========================================================================
// 7 · Four capability layers (the diagram)
// SAY: Four layers, bottom to top. Each publishes a contract. Arrows up are
//      dependencies on contracts, never on internals.
// ===========================================================================
#slide[
  #slide-heading(
    [Four capability layers],
    eyebrow: "The architecture",
    tag: layer-tag("L0") + h(0.2em) + layer-tag("L1") + h(0.2em)
      + layer-tag("L2") + h(0.2em) + layer-tag("L3"),
  )
  #v(0.2em)
  #align(center)[#image("architecture-components.pdf", width: 78%)]
  #v(0.3em)
  #align(center)[#text(size: 0.62em, fill: gray)[
    *L0* logical event-driven core (Kafka + Neo4j) · *L1* physical layout &
    travel times · *L2* geospatial + real-world feeds (ADS-B, METAR, BTS) ·
    *L3* decisional, actions return only through approval gates.
  ]]
]

// ===========================================================================
// 8 · How the loop closes (illustrated)
// SAY: Depend on contracts, not internals. L3 reads the shadow, proposes
//      decisions, and only re-enters through an approval gate and command
//      topics. That is why the decisional layer stays removable.
// ===========================================================================
#slide[
  #slide-heading([How the loop closes], eyebrow: "The architecture")

  #v(0.5em)
  #align(center)[#text(size: 0.9em, fill: ink)[
    A layer depends on the *contracts* of lower layers, #text(fill: navy, weight: "bold")[never on their internals.]
  ]]

  #v(1.3em)
  // Flow: shadow -> decisional -> approval gate, with a return path below.
  #let fbox(title, sub, accent) = box(
    width: 10.5em, inset: 0.8em, radius: 0.5em,
    fill: accent.lighten(88%), stroke: 1.4pt + accent,
  )[
    #align(center)[
      #text(size: 0.82em, weight: "bold", fill: accent.darken(15%))[#title]
      #v(0.25em)
      #text(size: 0.62em, fill: gray)[#sub]
    ]
  ]
  #let flowarrow(label) = stack(dir: ttb, spacing: 0.25em,
    align(center, text(size: 0.56em, fill: gray, style: "italic")[#label]),
    align(center, text(size: 1.3em, fill: gray)[➜]),
  )

  #align(center)[
    #grid(columns: (auto, auto, auto, auto, auto), align: horizon, column-gutter: 0.7em,
      fbox([Digital shadow], [L0-L2 · events, graph, geodata], blue-light),
      flowarrow([reads $C_0$-$C_2$]),
      fbox([Decisional layer], [L3 · anomalies, scenarios, appraisals], amber),
      flowarrow([proposes]),
      fbox([Approval gate], [human-in-the-loop], gray),
    )
  ]

  #v(0.9em)
  #align(center)[
    #box(inset: (x: 1em, y: 0.5em), radius: 0.4em, fill: navy.lighten(92%),
      stroke: (left: 3pt + navy, rest: 0pt))[
      #text(size: 0.72em, fill: navy)[
        ⟵ #h(0.3em) approved actions re-enter only through *command topics*
        (never through imports) #h(0.3em) ⟵
      ]
    ]
  ]

  #v(1em)
  #align(center)[#text(size: 0.78em, fill: gray)[
    Because L3 re-enters only through command topics, it stays
    #text(fill: navy, weight: "bold")[removable] from the shadow below.
  ]]
]

// ===========================================================================
// Divider ② : EVSK
// ===========================================================================
#air-divider-slide([02], [EVSK: the twin, actually running],
  note: [VirtualSky International Airport · an open-source, ongoing research prototype.])

// ===========================================================================
// 9 · What EVSK is + scale
// SAY: We didn't just argue it, we built a real, non-trivial twin to
//      instantiate all four layers and exercise the boundaries.
// ===========================================================================
#slide[
  #slide-heading([One instrument, four layers], eyebrow: "The prototype")

  #v(0.6em)
  #grid(columns: (1fr, 1fr, 1fr, 1fr), column-gutter: 0.8em,
    stat([9], "domain services", accent: layer-color.at("L0")),
    stat([420], "flights / sim day", accent: layer-color.at("L1")),
    stat([\~30k], "passengers / day", accent: layer-color.at("L2")),
    stat([3600×], "max sim clock", accent: layer-color.at("L3")),
  )
  #v(1em)
  #cols(gutter: 2em)[
    #text(weight: "bold", fill: navy)[The stack]
    #air-list(spacing: 0.4em)[
      - 9 FastAPI domain services + Node/Express gateway
      - Kafka event backbone
      - Neo4j graph as the single source of truth
      - React / TypeScript dashboards
      - LightGBM queue forecasting
      - Config-driven airport identity; Docker Compose; staged CI
    ]
  ][
    #text(weight: "bold", fill: navy)[The decisional layer, for real]
    #air-list(spacing: 0.4em, marker: text(amber)[▪])[
      - Anomaly detection, scenario & delay-cascade analysis
      - Cost / P&L, EC261 exposure, carbon, Monte-Carlo NPV and IRR
      - Gated recommendations: human-in-the-loop commands
    ]
  ]
]

// ===========================================================================
// 10 · The running twin (visual)
// SAY: Here it is alive. The graph is the single source of truth; dashboards
//      read it; and L2 lets you swap simulated vs. real-world feeds at runtime.
// ===========================================================================
#slide[
  #slide-heading([The twin, live], eyebrow: "The prototype")
  #v(0.5em)
  #grid(columns: (1.22fr, 1fr), column-gutter: 1.2em, align: top,
    [
      #box(radius: 0.4em, clip: true, stroke: 0.75pt + hair,
        image("visualisation.png", height: 352pt, fit: "contain"))
      #v(0.3em)
      #text(size: 0.6em, fill: gray)[*L0* · Neo4j graph, the single source of
        truth: airport, terminals, gates, runways, flights, passengers, weather.]
    ],
    stack(dir: ttb, spacing: 0.55em,
      [
        #box(radius: 0.4em, clip: true, stroke: 0.75pt + hair,
          image("cost-dashboard.png", height: 214pt, fit: "contain"))
        #v(0.15em)
        #text(size: 0.6em, fill: gray)[*L3* · cost / P&L dashboard.]
      ],
      [
        #box(radius: 0.4em, clip: true, stroke: 0.75pt + hair,
          image("data-sources-dashboard.png", height: 214pt, fit: "contain"))
        #v(0.15em)
        #text(size: 0.6em, fill: gray)[*L2* · swap simulated and live feeds at runtime.]
      ],
    ),
  )
]

// ===========================================================================
// 11 · Demo video
// SAY: This recording follows the running synthetic airport through its
//      operations, a disruption and the financial view.
// The self-contained slides.html plays the captioned recording in this frame.
// embed_pdf_video.py adds an in-page player and the MP4 bytes to the PDF.
// ===========================================================================
#slide[
  #slide-heading([The twin, running], eyebrow: "Recorded demonstration")

  // Fixed geometry matches the video frame in build_presenter.py.
  #place(top + left, dx: 0pt, dy: 120pt)[
    #box(width: 1160pt, height: 480pt, radius: 8pt, clip: true, fill: rgb("#101a27"),
      image("demo-poster.png", width: 1160pt, height: 480pt, fit: "contain"))
  ]
  #v(514pt)
  #align(center)[#text(size: 0.6em, fill: gray)[
    46-second recording · synthetic operations · English subtitles
  ]]
]

// ===========================================================================
// 12 · Spec-first + RQ2 + honesty
// SAY: EVSK was built with AI-assisted, specification-first development.
//      Specs and skill files instructed the coding agents. RQ2 asks whether
//      those instructions preserve contracts. Audits were still necessary.
// ===========================================================================
#slide[
  #slide-heading(
    [Keeping contracts honest: specification-first],
    eyebrow: "The methodology", tag: rq2,
  )

  #v(0.35em)
  #text(size: 0.96em, weight: "bold", fill: navy)[EVSK was built with AI-assisted, specification-first development.]
  #v(0.2em)
  #text(size: 0.78em, fill: gray)[Service specifications and skill files guided the AI coding agents before implementation.]
  #v(0.6em)
  #callout(accent: navy, fill: card)[
    #text(size: 0.84em)[
      #text(weight: "bold", fill: navy)[RQ2] #h(0.5em) To what extent does
      specification-first development *preserve architectural contracts* during
      sustained implementation, and *where does it need independent verification?*
    ]
  ]

  #v(0.9em)
  #grid(columns: (auto, 1fr), row-gutter: 0.7em, column-gutter: 0.9em, align: (right + horizon, left + horizon),
    text(size: 0.72em, weight: "bold", fill: navy)[Specs are\ authoritative],
    box[
      #chip([event schemas], accent: navy) #h(0.3em)
      #chip([Neo4j data model], accent: navy) #h(0.3em)
      #chip([SimClock rules], accent: navy) #h(0.3em)
      #chip([`SPEC.md` per service], accent: navy) #h(0.3em)
      #chip([skill files], accent: navy)
    ],
    text(size: 0.72em, weight: "bold", fill: green)[Guardrails],
    box[
      #chip([no wall-clock in logic], accent: green) #h(0.3em)
      #chip([no service-to-service HTTP], accent: green) #h(0.3em)
      #chip([no silent mutations], accent: green) #h(0.3em)
      #chip([graph = source of truth], accent: green) #h(0.3em)
      #chip([contract & fidelity tests], accent: green)
    ],
  )

  #v(1em)
  #callout(accent: amber)[
    #text(size: 0.78em)[
      #text(weight: "bold")[But specs alone were not enough.] #gap #h(0.3em) A
      mid-project audit found constants that had duplicated *and diverged*,
      recommendations never wired to command topics, and an ML endpoint that
      reported success *without training a model.* Each fix went back into the skill files.
    ]
  ]
]

// ===========================================================================
// Divider ③ : evidence
// ===========================================================================
#air-divider-slide([03], [Does the principle actually hold?],
  note: [A retrospective audit of four real fidelity upgrades in the repository history.])

// ===========================================================================
// 13 · Blast radius (evidence, clarified)
// SAY: We traced four upgrades from their first commit and measured how far
//      each one spread. The headline: 3 of 4 were purely additive. One (BTS)
//      reached into lower-layer internals; let me explain exactly why.
// ===========================================================================
#slide[
  #slide-heading([Blast radius of four fidelity upgrades], eyebrow: "Evidence", tag: rq1)

  #v(0.4em)
  // Conclusion upfront so the chart is read as evidence, not mystery.
  #callout(accent: green, fill: card)[
    #text(size: 0.76em)[
      *3 of 4 upgrades touched only new code.* No existing consumer needed an
      interface migration.
    ]
  ]
  #v(0.55em)

  // Column header explaining the annotation format.
  #grid(columns: (5em, 1fr, 9.5em), column-gutter: 0.8em,
    align: (right + horizon, left + horizon, left + horizon),
    [],
    text(size: 0.5em, fill: gray, tracking: 0.04em)[
      #upper("unique scoped files  (bar width proportional to L3, the largest upgrade)")
    ],
    text(size: 0.5em, fill: gray)[#upper("added / existing edited / components")],
  )
  #v(0.2em)

  #stack(dir: ttb, spacing: 0.55em,
    hbar([L1 geometry], 14/35, layer-color.at("L1"), [14 / 6 / 5  additive]),
    hbar([L2 feeds],    17/35, layer-color.at("L2"), [17 / 9 / 7  additive]),
    hbar([BTS calib.],   7/35, amber,                [7 / 5 / 3   L0 edit]),
    hbar([L3 cost],     35/35, layer-color.at("L3"), [35 / 12 / 6  additive]),
  )

  #v(0.7em)
  #callout(accent: amber)[
    #text(size: 0.74em)[
      *BTS calibration: why it is different.* L0 exposed no input port for
      calibrated parameters. Calibration therefore had to edit the schedule
      generator and passenger generator directly. *Contracts stayed stable;
      internals did not.* The fix: adding a dedicated calibration input port to L0.
    ]
  ]
]

// ===========================================================================
// 14 · Findings
// SAY: RQ1: contract preservation held across all four, including the one that
//      reached into L0. RQ2: spec-first helps but is not sufficient; you need
//      tests, audits and human review.
// ===========================================================================
#slide[
  #slide-heading([What we found], eyebrow: "Findings", tag: finding)

  #v(0.8em)
  #cols(gutter: 2em)[
    #card-panel(accent: navy)[
      #text(weight: "bold", fill: navy)[RQ1 · contract preservation]
      #v(0.6em)
      #air-list(spacing: 0.85em)[
        - All four paths preserved existing event & service contracts.
        - *No* existing consumer needed an interface migration.
        - Supports *append-only* contracts: preservation of the contract, not a
          promise of zero lower-layer edits (see BTS).
      ]
    ]
  ][
    #card-panel(accent: green)[
      #text(weight: "bold", fill: green)[RQ2 · specification-first]
      #v(0.6em)
      #air-list(spacing: 0.85em, marker: text(green)[▪])[
        - Specs, skill files and hard rules *help*, but are *not* sufficient alone.
        - Contract tests, fidelity regressions and audits are necessary complements.
        - Architecture says what must stay stable; methodology helps preserve it.
      ]
    ]
  ]
]

// ===========================================================================
// 15 · Perspectives and next steps
// SAY: EVSK is an ongoing prototype. Here is where the work goes next, both
//      as open research questions and as concrete planned improvements.
// ===========================================================================
#slide[
  #slide-heading([Perspectives and next steps], eyebrow: "Outlook")

  #v(0.9em)
  #cols(gutter: 2.2em)[
    #text(weight: "bold", fill: navy)[Open questions]
    #air-list(spacing: 0.85em)[
      - When does a contract *need* to be versioned rather than extended?
      - Can contract preservation be checked automatically at CI time, without a manual audit?
      - How does the architecture behave in non-event-driven stacks (REST-only, streaming)?
    ]
  ][
    #text(weight: "bold", fill: green)[Planned work]
    #text(size: 0.85em)[
      #air-list(spacing: 0.65em, marker: text(green)[▪])[
        - *Compare architectures*: run the same upgrades on monolithic and other layered twins. Measure changed files, contract breaks and implementation effort.
        - Test generality in a second domain, such as a port or hospital
        - Formalise contracts for static or property-based checks
        - Audit the next fidelity upgrade as it happens
      ]
    ]
  ]

  #v(1.1em)
  #callout(accent: blue-light, fill: card)[
    #text(size: 0.82em)[
      EVSK is active and open. Contributions and replication studies welcome.
      #h(0.5em)
      #link("https://github.com/arthur-chevallier/airport-digital-twin")[
        #text(fill: blue-light)[github.com/arthur-chevallier/airport-digital-twin]
      ]
    ]
  ]
]

// ===========================================================================
// 16 · Takeaway
// SAY: The ordering isn't about airports. Event state, space, observed data,
//      then decisions is a general recipe: hospitals, ports, warehouses, cities.
// ===========================================================================
#air-hero-slide(
  [Treat fidelity growth as a first-class\ architectural constraint, and verify it.],
  eyebrow: "Takeaway",
  sub: [
    The same ordering generalises far beyond airports:
    event state, space, observed data, decisions.
  ],
  accent: navy,
)

// ===========================================================================
// 17 · Thanks / Q&A
// ===========================================================================
#air-closing-slide([Thank you],
  note: [
    Questions welcome.
    #v(1.0em)
    #box(inset: (x: 0.8em, y: 0.45em), radius: 0.35em,
      fill: white.transparentize(88%), stroke: 1pt + on-navy-dim)[
      #text(size: 0.68em, weight: "bold")[
        #link("https://github.com/arthur-chevallier/airport-digital-twin")[github.com/arthur-chevallier/airport-digital-twin]
      ]
    ]
    #v(1.2em)
    #text(size: 0.72em)[A Layered Architecture for Digital Twins with Progressive Fidelity]
    #linebreak()
    #text(size: 0.66em, fill: on-navy-dim)[
      Arthur Chevallier · German Castignani · Luxembourg Institute of Science and Technology
      #linebreak()
      EVSK is open source · all data synthetic except opt-in L2 live feeds
    ]
  ],
)
