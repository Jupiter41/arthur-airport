#import "@preview/charged-ieee:0.1.4": ieee

#show: ieee.with(
  title: [Designing Digital Twins for Progressive Fidelity: A Layered Architecture for Airport Operations Modelling with AI-Assisted Development],
  abstract: [
    Digital twins of complex cyber-physical systems are typically built as monolithic, closed-loop models that are difficult to extend and impossible to reproduce. We propose a layered fidelity architecture in which a digital twin begins as a pure event-driven simulation and progressively acquires physical, geospatial, and decisional capabilities - each phase building on the previous without architectural rewrites. To demonstrate this approach, we present Arthur International Airport (KART), a fully open-source, airport digital twin implemented using a specification-first development methodology with AI coding agent assistance. We show that structuring domain knowledge as machine-readable specification and skill files - readable by both human developers and large language model agents - reduces architectural errors and revision cycles in complex system development. The resulting system models flight operations, passenger flows, baggage handling, weather impacts, and hazardous incident cascades across seven microservices, with several layers such as LLM and a real-time geospatial interface. All artefacts, including specifications, skill files, and infrastructure code, are publicly available.
  ],
  authors: (
    (
      name: "Arthur Chevallier",
      department: [],
      organization: [],
      location: [France],
      email: "arthurprivate@laposte.net",
    ),
  ),
  index-terms: (
    "Digital twins",
    "Airport operations",
    "Cyber-physical systems",
    "AI-assisted software engineering",
    "Specification-driven development",
    "Simulation architecture",
    "Progressive fidelity",
  ),
  bibliography: bibliography("refs.bib"),
  figure-supplement: [Fig.],
)


= Introduction



= Related Work



= Layered Fidelity Architecture <sec:architecture>


= Specification-First Development with AI Agent Integration <sec:methodology>


= The KART Implementation <sec:implementation>


= Evaluation <sec:evaluation>


= Discussion <sec:discussion>


= Conclusion

