import { useEffect, useMemo, useRef, useState } from "react";
import "mapbox-gl/dist/mapbox-gl.css";
import "leaflet/dist/leaflet.css";
import { useFlightBoardQueries, useADSBQuery } from "../../hooks/useQueries";
import { useSimStore } from "../../stores/simStore";
import type { Flight, ADSBFeatureCollection } from "../../types";
import {
  KART_COORDINATES,
  computeAircraftPosition,
  destinationCoordinates,
} from "../../utils/geospatial";

interface PositionFeature {
  type: "Feature";
  geometry: { type: "Point"; coordinates: [number, number] };
  properties: {
    flight_id: string;
    flight_number: string;
    destination_iata: string;
    heading_deg: number;
    altitude_ft: number;
    status: string;
  };
}

interface RouteFeature {
  type: "Feature";
  geometry: { type: "LineString"; coordinates: [number, number][] };
  properties: {
    flight_id: string;
    flight_number: string;
    destination_iata: string;
  };
}

interface AirportFeature {
  type: "Feature";
  geometry: { type: "Point"; coordinates: [number, number] };
  properties: {
    iata: string;
    name: string;
    is_home: number;
  };
}

const EMPTY_FEATURE_COLLECTION = {
  type: "FeatureCollection" as const,
  features: [],
};

/** Match an ADS-B aircraft to a simulated flight by heading similarity and distance. */
function findMatchingAdsb(
  flight: Flight,
  simTime: string,
  adsbFeatures: ADSBFeatureCollection["features"],
): { callsign: string; lat: number; lon: number; deviationKm: number } | null {
  const pos = computeAircraftPosition(flight, simTime);
  if (!pos) return null;

  const dest = destinationCoordinates(flight.destination_iata);
  if (!dest) return null;

  const simHeading = pos.heading_deg;
  let best: { callsign: string; lat: number; lon: number; deviationKm: number } | null = null;
  let bestDist = Infinity;

  for (const f of adsbFeatures) {
    const heading = f.properties.heading;
    if (heading == null || f.properties.on_ground) continue;

    // Heading must be within 20°
    let headingDiff = Math.abs(heading - simHeading);
    if (headingDiff > 180) headingDiff = 360 - headingDiff;
    if (headingDiff > 20) continue;

    const [lon, lat] = f.geometry.coordinates;
    // Distance from ADS-B aircraft to the simulated position
    const latDiff = lat - pos.lat;
    const lonDiff = lon - pos.lon;
    const roughDistKm = Math.sqrt(latDiff ** 2 + lonDiff ** 2) * 111;

    if (roughDistKm < bestDist && roughDistKm < 500) {
      bestDist = roughDistKm;
      best = {
        callsign: f.properties.callsign,
        lat,
        lon,
        deviationKm: Math.round(roughDistKm * 10) / 10,
      };
    }
  }

  return best;
}

function toPositionFeature(
  flight: Flight,
  simTime: string,
): PositionFeature | null {
  const position = computeAircraftPosition(flight, simTime);
  if (!position) {
    return null;
  }

  return {
    type: "Feature",
    geometry: {
      type: "Point",
      coordinates: [position.lon, position.lat],
    },
    properties: {
      flight_id: flight.id,
      flight_number: flight.flight_number,
      destination_iata: flight.destination_iata,
      heading_deg: position.heading_deg,
      altitude_ft: position.altitude_ft,
      status: flight.status,
    },
  };
}

function toRouteFeature(flight: Flight): RouteFeature | null {
  const destination = destinationCoordinates(flight.destination_iata);
  if (!destination) {
    return null;
  }

  return {
    type: "Feature",
    geometry: {
      type: "LineString",
      coordinates: [
        [KART_COORDINATES.lon, KART_COORDINATES.lat],
        [destination.lon, destination.lat],
      ],
    },
    properties: {
      flight_id: flight.id,
      flight_number: flight.flight_number,
      destination_iata: flight.destination_iata,
    },
  };
}

export default function WorldMapPage() {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<unknown>(null);
  const routeLayerGroupRef = useRef<unknown>(null);
  const airportLayerGroupRef = useRef<unknown>(null);
  const aircraftMarkersRef = useRef<unknown[]>([]);

  const { flights, weather } = useFlightBoardQueries();
  const simTime = useSimStore((s) => s.status.sim_time);

  // ── Fix #2: keep always-fresh refs so Mapbox click handlers never go stale ──
  const activeFlightsRef = useRef<Flight[]>([]);
  const [selectedFlightId, setSelectedFlightId] = useState<string | null>(null);
  const [searchPlane, setSearchPlane] = useState<string>("");
  const [searchAirport, setSearchAirport] = useState<string>("");
  const [showSearchPanel, setShowSearchPanel] = useState(false);
  const [showAdsb, setShowAdsb] = useState(false);
  const [selectedAdsbInfo, setSelectedAdsbInfo] = useState<{
    callsign: string;
    altitude: string;
    speed: string;
    distance: string;
    country: string;
    icao24: string;
  } | null>(null);

  const adsbQuery = useADSBQuery(showAdsb);
  const adsbData = adsbQuery.data as ADSBFeatureCollection | undefined;

  const token = (
    import.meta.env.VITE_MAPBOX_TOKEN as string | undefined
  )?.trim();
  const hasMapboxToken = Boolean(token);

  const activeFlights = useMemo(
    () =>
      (flights.data ?? []).filter((flight) => flight.direction === "departure"),
    [flights.data],
  );

  // Keep refs in sync on every render
  activeFlightsRef.current = activeFlights;

  const filteredPlanes = useMemo(() => {
    if (!searchPlane) return activeFlights;
    const query = searchPlane.toLowerCase();
    return activeFlights.filter(
      (f) =>
        f.flight_number.toLowerCase().includes(query) ||
        f.airline_code.toLowerCase().includes(query) ||
        f.destination_iata.toLowerCase().includes(query),
    );
  }, [activeFlights, searchPlane]);

  const filteredAirports = useMemo(() => {
    if (!searchAirport) return [];
    const query = searchAirport.toLowerCase();
    const seen = new Set<string>();
    return activeFlights
      .filter((f) => {
        if (seen.has(f.destination_iata)) return false;
        seen.add(f.destination_iata);
        return f.destination_iata.toLowerCase().includes(query);
      })
      .map((f) => f.destination_iata);
  }, [activeFlights, searchAirport]);

  const selectedFlight = useMemo(
    () =>
      filteredPlanes.find((flight) => flight.id === selectedFlightId) ?? null,
    [filteredPlanes, selectedFlightId],
  );

  const selectPlane = (flightId: string) => {
    const flight = activeFlightsRef.current.find((f) => f.id === flightId);
    if (!flight) return;

    setSelectedFlightId(flightId);
  };

  const flyToAirport = (iata: string) => {
    const coords = destinationCoordinates(iata);
    if (!coords || !mapRef.current) return;

    if ((mapRef.current as any).flyTo) {
      (mapRef.current as any).flyTo?.({
        center: [coords.lon, coords.lat],
        zoom: 9,
        duration: 1500,
        pitch: 30,
      });
    } else {
      (mapRef.current as any).flyTo?.([coords.lat, coords.lon], 9, {
        duration: 1.5,
      });
    }
  };

  const positionFeatures = useMemo(
    () =>
      activeFlights
        .map((flight) => toPositionFeature(flight, simTime))
        .filter((feature): feature is PositionFeature => Boolean(feature)),
    [activeFlights, simTime],
  );

  const routeFeatures = useMemo(
    () =>
      activeFlights
        .map((flight) => toRouteFeature(flight))
        .filter((feature): feature is RouteFeature => Boolean(feature)),
    [activeFlights],
  );

  const airportFeatures = useMemo(() => {
    const features: AirportFeature[] = [
      {
        type: "Feature",
        geometry: {
          type: "Point",
          coordinates: [KART_COORDINATES.lon, KART_COORDINATES.lat],
        },
        properties: {
          iata: "KART",
          name: "Arthur International Airport",
          is_home: 1,
        },
      },
    ];

    const seen = new Set<string>();
    for (const flight of activeFlights) {
      if (seen.has(flight.destination_iata)) {
        continue;
      }
      const destination = destinationCoordinates(flight.destination_iata);
      if (!destination) {
        continue;
      }
      seen.add(flight.destination_iata);
      features.push({
        type: "Feature",
        geometry: {
          type: "Point",
          coordinates: [destination.lon, destination.lat],
        },
        properties: {
          iata: flight.destination_iata,
          name: `Airport ${flight.destination_iata}`,
          is_home: 0,
        },
      });
    }

    return features;
  }, [activeFlights]);

  const stats = useMemo(() => {
    const airborne = activeFlights.filter(
      (f) => f.status === "airborne",
    ).length;
    const approach = activeFlights.filter(
      (f) => f.status === "approach",
    ).length;
    const longHaul = activeFlights.filter(
      (f) => f.route_category === "long_haul",
    ).length;
    const longest = activeFlights
      .filter((f) => f.route_category === "long_haul")
      .sort((a, b) => b.delay_minutes - a.delay_minutes)[0];

    return {
      airborne,
      approach,
      longHaul,
      longest: longest?.flight_number ?? "-",
    };
  }, [activeFlights]);

  // Track comparison: match selected simulated flight with a nearby ADS-B aircraft
  const trackComparison = useMemo(() => {
    if (!showAdsb || !selectedFlight || !adsbData?.features.length) return null;
    return findMatchingAdsb(selectedFlight, simTime, adsbData.features);
  }, [showAdsb, selectedFlight, adsbData, simTime]);

  useEffect(() => {
    if (!mapContainerRef.current) {
      return;
    }

    if (hasMapboxToken) {
      let disposed = false;
      void (async () => {
        const mapboxgl = (await import("mapbox-gl")).default;
        mapboxgl.accessToken = token as string;

        const map = new mapboxgl.Map({
          container: mapContainerRef.current as HTMLElement,
          style: "mapbox://styles/mapbox/satellite-streets-v12",
          center: [KART_COORDINATES.lon, KART_COORDINATES.lat],
          zoom: 3,
          pitch: 34,
          antialias: true,
        });

        mapRef.current = map;
        map.addControl(
          new mapboxgl.NavigationControl({ showCompass: true }),
          "top-right",
        );

        map.on("load", () => {
          if (disposed) {
            return;
          }

          const staticSources = [
            "apron",
            "runways",
            "taxiways",
            "terminals",
            "gates",
          ];

          for (const sourceId of staticSources) {
            map.addSource(sourceId, {
              type: "geojson",
              data: `/geojson/${sourceId}.geojson`,
            });
          }

          map.addSource("airports", {
            type: "geojson",
            data: EMPTY_FEATURE_COLLECTION,
          });
          map.addSource("routes", {
            type: "geojson",
            lineMetrics: true,
            data: EMPTY_FEATURE_COLLECTION,
          });
          map.addSource("aircraft", {
            type: "geojson",
            data: EMPTY_FEATURE_COLLECTION,
          });
          map.addSource("adsb-aircraft", {
            type: "geojson",
            data: EMPTY_FEATURE_COLLECTION,
          });

          map.addLayer({
            id: "routes-line",
            type: "line",
            source: "routes",
            paint: {
              "line-color": "#22d3ee",
              "line-width": ["interpolate", ["linear"], ["zoom"], 2, 1.5, 8, 3],
              "line-dasharray": [2, 2],
              "line-opacity": 0.75,
            },
          });

          map.addLayer({
            id: "apron-fill",
            type: "fill",
            source: "apron",
            paint: {
              "fill-color": "#5c6873",
              "fill-opacity": 0.55,
            },
          });

          map.addLayer({
            id: "apron-outline",
            type: "line",
            source: "apron",
            paint: {
              "line-color": "#8b95a5",
              "line-width": [
                "interpolate",
                ["linear"],
                ["zoom"],
                2,
                0.3,
                13,
                1,
              ],
              "line-opacity": 0.6,
            },
          });

          map.addLayer({
            id: "runways-fill",
            type: "fill-extrusion",
            source: "runways",
            paint: {
              "fill-extrusion-color": "#1a1d22",
              "fill-extrusion-height": ["coalesce", ["get", "height_m"], 1.5],
              "fill-extrusion-opacity": 0.98,
            },
          });

          map.addLayer({
            id: "taxiways-line",
            type: "line",
            source: "taxiways",
            paint: {
              "line-color": "#fcd34d",
              "line-width": [
                "interpolate",
                ["linear"],
                ["zoom"],
                2,
                0.8,
                13,
                4,
              ],
              "line-opacity": 0.85,
            },
          });

          map.addLayer({
            id: "terminals-fill",
            type: "fill",
            source: "terminals",
            paint: {
              "fill-color": "#1e7aa3",
              "fill-opacity": 0.65,
            },
          });

          map.addLayer({
            id: "terminals-outline",
            type: "line",
            source: "terminals",
            paint: {
              "line-color": "#4db8d4",
              "line-width": [
                "interpolate",
                ["linear"],
                ["zoom"],
                2,
                0.5,
                13,
                2,
              ],
              "line-opacity": 0.9,
            },
          });

          map.addLayer({
            id: "gates-circles",
            type: "circle",
            source: "gates",
            paint: {
              "circle-color": "#06b6d4",
              "circle-radius": [
                "interpolate",
                ["linear"],
                ["zoom"],
                8,
                3,
                14,
                6,
              ],
              "circle-opacity": 0.95,
              "circle-stroke-color": "#164e63",
              "circle-stroke-width": 1.5,
            },
            minzoom: 10,
          });

          map.addLayer({
            id: "gates-labels",
            type: "symbol",
            source: "gates",
            layout: {
              "text-field": ["get", "id"],
              "text-size": ["interpolate", ["linear"], ["zoom"], 12, 9, 14, 12],
              "text-offset": [0, 0],
              "text-allow-overlap": true,
            },
            paint: {
              "text-color": "#f8fafc",
              "text-halo-color": "#0a2a33",
              "text-halo-width": 2,
            },
            minzoom: 12,
          });

          map.addLayer({
            id: "airports-circles",
            type: "circle",
            source: "airports",
            paint: {
              "circle-color": [
                "case",
                ["==", ["get", "is_home"], 1],
                "#ffd166",
                "#8cc8ff",
              ],
              "circle-stroke-color": "#041321",
              "circle-stroke-width": 1,
              "circle-radius": [
                "interpolate",
                ["linear"],
                ["zoom"],
                2,
                3,
                8,
                5,
              ],
            },
          });

          map.addLayer({
            id: "airports-labels",
            type: "symbol",
            source: "airports",
            layout: {
              "text-field": ["get", "iata"],
              "text-size": 11,
              "text-offset": [0, 1.15],
              "text-allow-overlap": true,
            },
            paint: {
              "text-color": "#f2fbff",
              "text-halo-color": "#0b1118",
              "text-halo-width": 1,
            },
          });

          // Use inline SVG data URLs for stable icon rendering.
          const planeSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
            <path d="M24 4 L29 18 L44 22 L29 26 L26 44 L24 40 L22 44 L19 26 L4 22 L19 18 Z"
                  fill="#22d3ee" stroke="#0a2a33" stroke-width="1.5" stroke-linejoin="round"/>
          </svg>`;
          const selectedPlaneSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
            <path d="M24 4 L29 18 L44 22 L29 26 L26 44 L24 40 L22 44 L19 26 L4 22 L19 18 Z"
                  fill="#facc15" stroke="#0a2a33" stroke-width="1.5" stroke-linejoin="round"/>
          </svg>`;
          const planeSvgUrl =
            "data:image/svg+xml;charset=utf-8," + encodeURIComponent(planeSvg);
          const selectedPlaneSvgUrl =
            "data:image/svg+xml;charset=utf-8," +
            encodeURIComponent(selectedPlaneSvg);

          const planeImg = new Image(48, 48);
          planeImg.onload = () => {
            if (map.hasImage("plane-icon")) map.removeImage("plane-icon");
            map.addImage("plane-icon", planeImg);

            const selectedPlaneImg = new Image(48, 48);
            selectedPlaneImg.onload = () => {
              if (map.hasImage("plane-icon-selected")) {
                map.removeImage("plane-icon-selected");
              }
              map.addImage("plane-icon-selected", selectedPlaneImg);

              map.addLayer({
                id: "aircraft-symbols",
                type: "symbol",
                source: "aircraft",
                layout: {
                  "icon-image": [
                    "case",
                    ["==", ["get", "flight_id"], selectedFlightId ?? ""],
                    "plane-icon-selected",
                    "plane-icon",
                  ],
                  "icon-size": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    2,
                    0.45,
                    8,
                    0.75,
                    14,
                    1.1,
                  ],
                  "icon-rotate": ["coalesce", ["get", "heading_deg"], 0],
                  "icon-rotation-alignment": "map",
                  "icon-allow-overlap": true,
                  "icon-keep-upright": false,
                  "text-field": ["get", "flight_number"],
                  "text-size": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    3,
                    7,
                    8,
                    10,
                    12,
                    12,
                  ],
                  "text-offset": [0, 2],
                  "text-allow-overlap": true,
                },
                paint: {
                  "text-color": "#d5f4ff",
                  "text-halo-color": "#0b1118",
                  "text-halo-width": 1,
                },
              });

              map.on("click", "aircraft-symbols", (event) => {
                const flightId = event.features?.[0]?.properties?.flight_id as
                  | string
                  | undefined;
                if (flightId) {
                  selectPlane(flightId);
                }
              });

              map.on("mouseenter", "aircraft-symbols", () => {
                map.getCanvas().style.cursor = "pointer";
              });
              map.on("mouseleave", "aircraft-symbols", () => {
                map.getCanvas().style.cursor = "";
              });

              // ── ADS-B layer (real aircraft — orange icons) ──
              const adsbSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
                <path d="M24 4 L29 18 L44 22 L29 26 L26 44 L24 40 L22 44 L19 26 L4 22 L19 18 Z"
                      fill="#f97316" stroke="#0a2a33" stroke-width="1.5" stroke-linejoin="round"/>
              </svg>`;
              const adsbSvgUrl =
                "data:image/svg+xml;charset=utf-8," +
                encodeURIComponent(adsbSvg);
              const adsbImg = new Image(48, 48);
              adsbImg.onload = () => {
                if (map.hasImage("adsb-icon")) map.removeImage("adsb-icon");
                map.addImage("adsb-icon", adsbImg);

                map.addLayer({
                  id: "adsb-symbols",
                  type: "symbol",
                  source: "adsb-aircraft",
                  layout: {
                    "icon-image": "adsb-icon",
                    "icon-size": [
                      "interpolate",
                      ["linear"],
                      ["zoom"],
                      2,
                      0.35,
                      8,
                      0.6,
                      14,
                      0.9,
                    ],
                    "icon-rotate": ["coalesce", ["get", "heading"], 0],
                    "icon-rotation-alignment": "map",
                    "icon-allow-overlap": true,
                    "icon-keep-upright": false,
                    "text-field": ["get", "callsign"],
                    "text-size": [
                      "interpolate",
                      ["linear"],
                      ["zoom"],
                      3,
                      7,
                      8,
                      9,
                      12,
                      11,
                    ],
                    "text-offset": [0, 2],
                    "text-allow-overlap": true,
                    "visibility": "none",
                  },
                  paint: {
                    "text-color": "#fed7aa",
                    "text-halo-color": "#0b1118",
                    "text-halo-width": 1,
                  },
                });

                map.on("click", "adsb-symbols", (event) => {
                  const props = event.features?.[0]?.properties;
                  if (props) {
                    const callsign = String(props.callsign ?? "").trim();
                    const alt = props.altitude_m != null ? `${Math.round(Number(props.altitude_m))}m` : "—";
                    const speed = props.velocity_ms != null ? `${Math.round(Number(props.velocity_ms) * 1.944)}kt` : "—";
                    const dist = `${Number(props.distance_km).toFixed(0)}km`;
                    setSelectedAdsbInfo({
                      callsign,
                      altitude: alt,
                      speed,
                      distance: dist,
                      country: String(props.origin_country ?? ""),
                      icao24: String(props.icao24 ?? ""),
                    });
                  }
                });

                map.on("mouseenter", "adsb-symbols", () => {
                  map.getCanvas().style.cursor = "pointer";
                });
                map.on("mouseleave", "adsb-symbols", () => {
                  map.getCanvas().style.cursor = "";
                });
              };
              adsbImg.src = adsbSvgUrl;
            };
            selectedPlaneImg.src = selectedPlaneSvgUrl;
          };
          planeImg.src = planeSvgUrl;

          map.on("zoom", () => {
            if (!map.isStyleLoaded()) {
              return;
            }

            const detailVisible = map.getZoom() >= 13;
            if (map.getLayer("gates-circles")) {
              map.setLayoutProperty(
                "gates-circles",
                "visibility",
                detailVisible ? "visible" : "none",
              );
            }
            if (map.getLayer("gates-labels")) {
              map.setLayoutProperty(
                "gates-labels",
                "visibility",
                detailVisible ? "visible" : "none",
              );
            }
          });
        });
      })();

      return () => {
        disposed = true;
        const maybeMap = mapRef.current as { remove?: () => void } | null;
        maybeMap?.remove?.();
        mapRef.current = null;
      };
    }

    let disposed = false;
    void (async () => {
      const L = await import("leaflet");
      const map = L.map(mapContainerRef.current as HTMLElement, {
        center: [KART_COORDINATES.lat, KART_COORDINATES.lon],
        zoom: 3,
      });
      mapRef.current = map;

      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap contributors",
      }).addTo(map);

      const files = ["apron", "runways", "taxiways", "terminals", "gates"];
      for (const file of files) {
        const response = await fetch(`/geojson/${file}.geojson`);
        const payload = await response.json();
        if (disposed) {
          return;
        }
        L.geoJSON(payload, {
          pointToLayer: (_feature, latlng) =>
            L.circleMarker(latlng, {
              radius: 4,
              color: "#8cf7d4",
              weight: 1,
              fillOpacity: 0.8,
            }),
          style: () => ({
            color: "#7ea7cf",
            weight: 2,
            fillOpacity: 0.25,
            fillColor: "#33506b",
          }),
        }).addTo(map);
      }

      routeLayerGroupRef.current = L.layerGroup().addTo(map);
      airportLayerGroupRef.current = L.layerGroup().addTo(map);
    })();

    return () => {
      disposed = true;
      const maybeMap = mapRef.current as { remove?: () => void } | null;
      maybeMap?.remove?.();
      mapRef.current = null;
      aircraftMarkersRef.current = [];
      routeLayerGroupRef.current = null;
      airportLayerGroupRef.current = null;
    };
  }, [hasMapboxToken, token]);

  useEffect(() => {
    if (!mapRef.current) {
      return;
    }

    if (hasMapboxToken) {
      const map = mapRef.current as {
        getSource: (
          name: string,
        ) => { setData?: (data: unknown) => void } | undefined;
        isStyleLoaded?: () => boolean;
        getLayer?: (layerId: string) => unknown;
        setLayoutProperty?: (
          layerId: string,
          name: string,
          value: unknown,
        ) => void;
      };

      map
        .getSource("routes")
        ?.setData?.({ type: "FeatureCollection", features: routeFeatures });
      map
        .getSource("aircraft")
        ?.setData?.({ type: "FeatureCollection", features: positionFeatures });
      map
        .getSource("airports")
        ?.setData?.({ type: "FeatureCollection", features: airportFeatures });

      // Update ADS-B source
      if (adsbData?.features) {
        map.getSource("adsb-aircraft")?.setData?.(adsbData);
      }

      // Toggle ADS-B layer visibility
      if (map.isStyleLoaded?.() && map.getLayer?.("adsb-symbols")) {
        map.setLayoutProperty?.(
          "adsb-symbols",
          "visibility",
          showAdsb ? "visible" : "none",
        );
      }

      if (map.isStyleLoaded?.() && map.getLayer?.("aircraft-symbols")) {
        map.setLayoutProperty?.("aircraft-symbols", "icon-image", [
          "case",
          ["==", ["get", "flight_id"], selectedFlightId ?? ""],
          "plane-icon-selected",
          "plane-icon",
        ]);
      }
      return;
    }

    void (async () => {
      const L = await import("leaflet");
      const map = mapRef.current as { removeLayer?: (layer: unknown) => void };
      const routeGroup = routeLayerGroupRef.current as {
        clearLayers?: () => void;
        addLayer?: (layer: unknown) => void;
      } | null;
      const airportGroup = airportLayerGroupRef.current as {
        clearLayers?: () => void;
        addLayer?: (layer: unknown) => void;
      } | null;

      routeGroup?.clearLayers?.();
      airportGroup?.clearLayers?.();

      aircraftMarkersRef.current.forEach((marker) => map.removeLayer?.(marker));
      aircraftMarkersRef.current = [];

      for (const route of routeFeatures) {
        const latlngs = route.geometry.coordinates.map(
          (coord) => [coord[1], coord[0]] as [number, number],
        );
        const line = L.polyline(latlngs, {
          color: "#66d3ff",
          dashArray: "6, 8",
          opacity: 0.55,
          weight: 2,
        });
        routeGroup?.addLayer?.(line);
      }

      for (const airport of airportFeatures) {
        const [lon, lat] = airport.geometry.coordinates;
        const marker = L.circleMarker([lat, lon], {
          radius: airport.properties.is_home === 1 ? 6 : 4,
          color: airport.properties.is_home === 1 ? "#ffd166" : "#8cc8ff",
          fillColor: airport.properties.is_home === 1 ? "#ffd166" : "#8cc8ff",
          fillOpacity: 0.9,
          weight: 1,
        }).bindTooltip(airport.properties.iata);
        airportGroup?.addLayer?.(marker);
      }

      for (const feature of positionFeatures) {
        const isSelected = feature.properties.flight_id === selectedFlightId;
        const fill = isSelected ? "#facc15" : "#22d3ee";
        const heading = feature.properties.heading_deg ?? 0;
        const icon = L.divIcon({
          className: "",
          iconSize: [28, 28],
          iconAnchor: [14, 14],
          html: `<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 48 48"
                      style="transform:rotate(${heading}deg)">
                   <path d="M24 4 L29 18 L44 22 L29 26 L26 44 L24 40 L22 44 L19 26 L4 22 L19 18 Z"
                         fill="${fill}" stroke="#0a2a33" stroke-width="1.5" stroke-linejoin="round"/>
                 </svg>`,
        });
        const marker = L.marker(
          [feature.geometry.coordinates[1], feature.geometry.coordinates[0]],
          { icon },
        )
          .bindTooltip(String(feature.properties.flight_number))
          .on("click", () => {
            selectPlane(feature.properties.flight_id);
          });

        marker.addTo(map as never);
        aircraftMarkersRef.current.push(marker);
      }
    })();
  }, [
    adsbData,
    airportFeatures,
    hasMapboxToken,
    positionFeatures,
    routeFeatures,
    selectedFlightId,
    showAdsb,
  ]);

  return (
    <section className="h-full w-full flex flex-col bg-slate-950">
      <div className="px-4 py-2 border-b border-slate-800 bg-slate-900/95">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h1 className="text-sm sm:text-base font-semibold text-slate-100">
              Arthur Airport - World View
            </h1>
            <p className="text-xs text-slate-400">
              {hasMapboxToken
                ? "Mapbox satellite with real destination airports"
                : "Leaflet OpenStreetMap fallback"}
              {" | Sim Time "}
              {new Date(simTime).toISOString()}
            </p>
          </div>
          <div className="text-xs text-slate-300 flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShowSearchPanel(!showSearchPanel)}
              className="px-3 py-1 rounded bg-cyan-600 hover:bg-cyan-700 transition-colors text-white font-medium"
              title="Toggle search panel"
            >
              🔍 Search
            </button>
            <button
              type="button"
              onClick={() => {
                setShowAdsb(!showAdsb);
                setSelectedAdsbInfo(null);
              }}
              className={`px-3 py-1 rounded transition-colors font-medium ${
                showAdsb
                  ? "bg-orange-600 hover:bg-orange-700 text-white"
                  : "bg-slate-700 hover:bg-slate-600 text-slate-300"
              }`}
              title="Toggle live ADS-B aircraft overlay"
            >
              📡 ADS-B {showAdsb && adsbData ? `(${adsbData.metadata.aircraft_count})` : ""}
            </button>
            <button
              type="button"
              onClick={() => {
                if (!mapRef.current) return;

                if (hasMapboxToken) {
                  const map = mapRef.current as {
                    flyTo?: (options: unknown) => void;
                  };
                  map.flyTo?.({
                    center: [KART_COORDINATES.lon, KART_COORDINATES.lat],
                    zoom: 8,
                    duration: 1500,
                  });
                } else {
                  const map = mapRef.current as {
                    flyTo?: (
                      latLng: unknown,
                      zoom: number,
                      options?: unknown,
                    ) => void;
                  };
                  map.flyTo?.([KART_COORDINATES.lat, KART_COORDINATES.lon], 8, {
                    duration: 1.5,
                  });
                }
              }}
              className="px-3 py-1 rounded bg-blue-600 hover:bg-blue-700 transition-colors text-white font-medium"
              title="Center to airport"
            >
              📍 Center
            </button>
          </div>
          <div className="text-xs text-slate-300 flex items-center gap-3">
            <span className="px-2 py-1 rounded bg-slate-800">
              Weather: {weather.data?.category ?? "-"}
            </span>
            <span className="px-2 py-1 rounded bg-slate-800">
              Airborne: {stats.airborne}
            </span>
            <span className="px-2 py-1 rounded bg-slate-800">
              Approach: {stats.approach}
            </span>
          </div>
        </div>
      </div>

      <div className="relative flex-1 min-h-0">
        <div ref={mapContainerRef} className="absolute inset-0" />

        {/* Search/Navigation Panel */}
        {showSearchPanel && (
          <div className="absolute top-3 left-3 w-80 rounded border border-slate-700 bg-slate-950/96 text-xs shadow-lg backdrop-blur-sm p-4 max-h-[70vh] overflow-y-auto animation-slide-right">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-semibold text-slate-100">
                Find Planes & Airports
              </h3>
              <button
                type="button"
                className="text-slate-400 hover:text-slate-200"
                onClick={() => setShowSearchPanel(false)}
              >
                ✕
              </button>
            </div>

            {/* Search Planes */}
            <div className="mb-4">
              <label className="block text-slate-400 mb-1">Search Planes</label>
              <input
                type="text"
                placeholder="Flight #, airline, destination..."
                value={searchPlane}
                onChange={(e) => setSearchPlane(e.target.value)}
                className="w-full px-2 py-1 rounded bg-slate-800 border border-slate-700 text-slate-100 placeholder-slate-500 text-xs focus:outline-none focus:ring-2 focus:ring-cyan-500"
              />
              <div className="mt-2 space-y-1">
                {filteredPlanes.slice(0, 10).map((flight) => (
                  <button
                    key={flight.id}
                    type="button"
                    onClick={() => selectPlane(flight.id)}
                    className={`w-full text-left px-2 py-1 rounded transition-colors text-xs ${
                      selectedFlightId === flight.id
                        ? "bg-cyan-600 text-white"
                        : "bg-slate-800 hover:bg-slate-700 text-slate-200"
                    }`}
                  >
                    <span className="font-mono font-semibold">
                      {flight.flight_number}
                    </span>
                    <span className="text-slate-400 mx-1">→</span>
                    <span>{flight.destination_iata}</span>
                    <span className="float-right text-slate-400">
                      {flight.status === "airborne" ? "✈️" : "🛫"}
                    </span>
                  </button>
                ))}
                {filteredPlanes.length === 0 && (
                  <div className="px-2 py-1 text-slate-500">
                    No planes found
                  </div>
                )}
                {filteredPlanes.length > 10 && (
                  <div className="px-2 py-1 text-slate-500 text-center">
                    +{filteredPlanes.length - 10} more...
                  </div>
                )}
              </div>
            </div>

            {/* Search Airports */}
            <div>
              <label className="block text-slate-400 mb-1">
                Search Airports
              </label>
              <input
                type="text"
                placeholder="IATA code..."
                value={searchAirport}
                onChange={(e) => setSearchAirport(e.target.value)}
                className="w-full px-2 py-1 rounded bg-slate-800 border border-slate-700 text-slate-100 placeholder-slate-500 text-xs focus:outline-none focus:ring-2 focus:ring-cyan-500"
              />
              <div className="mt-2 space-y-1">
                {filteredAirports.map((iata) => {
                  const flightCount = activeFlights.filter(
                    (f) => f.destination_iata === iata,
                  ).length;
                  return (
                    <button
                      key={iata}
                      type="button"
                      onClick={() => flyToAirport(iata)}
                      className="w-full text-left px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 transition-colors text-xs"
                    >
                      <span className="font-mono font-semibold">{iata}</span>
                      <span className="text-slate-400 mx-1">•</span>
                      <span className="text-slate-400">
                        {flightCount} flight{flightCount !== 1 ? "s" : ""}
                      </span>
                    </button>
                  );
                })}
                {filteredAirports.length === 0 && searchAirport && (
                  <div className="px-2 py-1 text-slate-500">
                    No airports found
                  </div>
                )}
              </div>

              {/* Quick stats */}
              <div className="mt-4 pt-4 border-t border-slate-700 space-y-1 text-slate-400">
                <div className="flex justify-between">
                  <span>Active Flights:</span>
                  <span className="font-semibold text-slate-200">
                    {activeFlights.length}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span>Unique Destinations:</span>
                  <span className="font-semibold text-slate-200">
                    {new Set(activeFlights.map((f) => f.destination_iata)).size}
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}

        {selectedFlight && (
          <aside className="absolute top-3 right-3 w-72 rounded border border-slate-700 bg-slate-950/96 text-xs shadow-lg backdrop-blur-sm p-3 animation-fade-in">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-sm font-semibold text-slate-100">
                {selectedFlight.flight_number}
              </h2>
              <button
                type="button"
                className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200"
                onClick={() => setSelectedFlightId(null)}
              >
                Close
              </button>
            </div>
            <div className="space-y-1 text-slate-300">
              <p>
                <span className="text-slate-400">Airline:</span>{" "}
                {selectedFlight.airline_code}
              </p>
              <p>
                <span className="text-slate-400">Aircraft:</span>{" "}
                {selectedFlight.aircraft_type}
              </p>
              <p>
                <span className="text-slate-400">Destination:</span>{" "}
                {selectedFlight.destination_iata}
              </p>
              <p>
                <span className="text-slate-400">Status:</span>{" "}
                <span
                  className={
                    selectedFlight.status === "airborne"
                      ? "text-cyan-400"
                      : selectedFlight.status === "approach"
                        ? "text-amber-400"
                        : selectedFlight.status === "delayed"
                          ? "text-red-400"
                          : "text-green-400"
                  }
                >
                  {selectedFlight.status}
                </span>
              </p>
              {selectedFlight.delay_minutes > 0 && (
                <p>
                  <span className="text-slate-400">Delay:</span>{" "}
                  <span className="text-amber-400">
                    {selectedFlight.delay_minutes} min
                  </span>
                </p>
              )}
              <p>
                <span className="text-slate-400">Terminal / Gate:</span>{" "}
                {selectedFlight.terminal} / {selectedFlight.gate_id ?? "-"}
              </p>
              <p>
                <span className="text-slate-400">Scheduled:</span>{" "}
                <span className="font-mono">
                  {new Date(selectedFlight.scheduled_time).toLocaleTimeString()}
                </span>
              </p>
              {selectedFlight.estimated_time &&
                selectedFlight.estimated_time !==
                  selectedFlight.scheduled_time && (
                  <p>
                    <span className="text-slate-400">Estimated:</span>{" "}
                    <span className="font-mono text-amber-400">
                      {new Date(
                        selectedFlight.estimated_time,
                      ).toLocaleTimeString()}
                    </span>
                  </p>
                )}
              {selectedFlight.pax_count > 0 && (
                <p>
                  <span className="text-slate-400">Passengers:</span>{" "}
                  {selectedFlight.pax_count} / {selectedFlight.seat_capacity}
                </p>
              )}
              {selectedFlight.flight_type && (
                <p>
                  <span className="text-slate-400">Type:</span>{" "}
                  {selectedFlight.flight_type} ({selectedFlight.route_category})
                </p>
              )}
            </div>

            {/* Track Comparison (P1-1-4) */}
            {showAdsb && trackComparison && (
              <div className="mt-3 pt-3 border-t border-slate-700">
                <h3 className="text-xs font-semibold text-orange-300 mb-1">
                  📡 Track Comparison
                </h3>
                <div className="space-y-1 text-slate-300">
                  <p>
                    <span className="text-slate-400">Matched ADS-B:</span>{" "}
                    <span className="font-mono text-orange-300">
                      {trackComparison.callsign}
                    </span>
                  </p>
                  <p>
                    <span className="text-slate-400">Deviation:</span>{" "}
                    <span
                      className={
                        trackComparison.deviationKm < 50
                          ? "text-green-400"
                          : trackComparison.deviationKm < 150
                            ? "text-amber-400"
                            : "text-red-400"
                      }
                    >
                      {trackComparison.deviationKm} km
                    </span>
                  </p>
                  <p className="text-[10px] text-slate-500">
                    Great-circle vs real ADS-B position
                  </p>
                </div>
              </div>
            )}
            {showAdsb && !trackComparison && selectedFlight.status === "airborne" && (
              <div className="mt-3 pt-3 border-t border-slate-700 text-[10px] text-slate-500">
                No nearby ADS-B match on similar heading
              </div>
            )}
          </aside>
        )}

        {/* ADS-B aircraft info popup */}
        {selectedAdsbInfo && !selectedFlight && (
          <aside className="absolute top-3 right-3 w-64 rounded border border-orange-700/50 bg-slate-950/96 text-xs shadow-lg backdrop-blur-sm p-3 animation-fade-in">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-sm font-semibold text-orange-300">
                📡 {selectedAdsbInfo.callsign || "Unknown"}
              </h2>
              <button
                type="button"
                className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200"
                onClick={() => setSelectedAdsbInfo(null)}
              >
                Close
              </button>
            </div>
            <div className="space-y-1 text-slate-300">
              <p>
                <span className="text-slate-400">ICAO24:</span>{" "}
                <span className="font-mono">{selectedAdsbInfo.icao24}</span>
              </p>
              <p>
                <span className="text-slate-400">Country:</span>{" "}
                {selectedAdsbInfo.country}
              </p>
              <p>
                <span className="text-slate-400">Altitude:</span>{" "}
                {selectedAdsbInfo.altitude}
              </p>
              <p>
                <span className="text-slate-400">Speed:</span>{" "}
                {selectedAdsbInfo.speed}
              </p>
              <p>
                <span className="text-slate-400">Distance to KART:</span>{" "}
                {selectedAdsbInfo.distance}
              </p>
            </div>
            <div className="mt-2 pt-2 border-t border-slate-700 text-[10px] text-slate-500">
              Live data from OpenSky Network
            </div>
          </aside>
        )}
      </div>

      <footer className="grid grid-cols-2 sm:grid-cols-5 gap-2 px-4 py-2 text-xs border-t border-slate-800 bg-slate-900">
        <div className="bg-slate-800/70 rounded px-2 py-1 text-slate-200">
          AIRBORNE: {stats.airborne}
        </div>
        <div className="bg-slate-800/70 rounded px-2 py-1 text-slate-200">
          ENROUTE &gt; 6H: {stats.longHaul}
        </div>
        <div className="bg-slate-800/70 rounded px-2 py-1 text-slate-200">
          APPROACHING: {stats.approach}
        </div>
        <div className="bg-slate-800/70 rounded px-2 py-1 text-slate-200">
          LONGEST: {stats.longest}
        </div>
        {showAdsb && (
          <div className="bg-orange-900/50 rounded px-2 py-1 text-orange-200">
            ADS-B: {adsbData?.metadata.aircraft_count ?? 0} real
          </div>
        )}
      </footer>
    </section>
  );
}
