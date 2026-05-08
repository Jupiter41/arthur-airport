import { useEffect, useMemo, useRef, useState } from "react";
import "mapbox-gl/dist/mapbox-gl.css";
import "leaflet/dist/leaflet.css";
import {
  useFlightBoardQueries,
  useADSBQuery,
  useNetworkStatusQuery,
} from "../../hooks/useQueries";
import { useSimStore } from "../../stores/simStore";
import type { Flight, ADSBFeatureCollection } from "../../types";
import type { NetworkStatus, NetworkArc } from "../../hooks/useApi";
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
    direction: string;
  };
}

interface RouteFeature {
  type: "Feature";
  geometry: { type: "LineString"; coordinates: [number, number][] };
  properties: {
    flight_id: string;
    flight_number: string;
    destination_iata: string;
    direction: string;
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
  let best: {
    callsign: string;
    lat: number;
    lon: number;
    deviationKm: number;
  } | null = null;
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
      direction: flight.direction,
    },
  };
}

function toRouteFeature(flight: Flight): RouteFeature | null {
  if (flight.direction === "arrival") {
    const origin = destinationCoordinates(flight.origin_iata);
    if (!origin) return null;
    return {
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [
          [origin.lon, origin.lat],
          [KART_COORDINATES.lon, KART_COORDINATES.lat],
        ],
      },
      properties: {
        flight_id: flight.id,
        flight_number: flight.flight_number,
        destination_iata: flight.destination_iata,
        direction: flight.direction,
      },
    };
  }

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
      direction: flight.direction,
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
  const [showNetwork, setShowNetwork] = useState(false);
  const [timelineActive, setTimelineActive] = useState(false);
  const [timelineOffset, setTimelineOffset] = useState(0); // minutes offset from sim start
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

  const networkQuery = useNetworkStatusQuery(showNetwork);
  const networkData = networkQuery.data as NetworkStatus | undefined;

  const token = (
    import.meta.env.VITE_MAPBOX_TOKEN as string | undefined
  )?.trim();
  const [mapboxFailed, setMapboxFailed] = useState(false);
  const hasMapboxToken = Boolean(token) && !mapboxFailed;

  const activeFlights = useMemo(
    () =>
      (flights.data ?? []).filter(
        (flight) =>
          flight.direction === "departure" || flight.direction === "arrival",
      ),
    [flights.data],
  );

  // Keep refs in sync on every render
  activeFlightsRef.current = activeFlights;

  const filteredPlanes = useMemo(() => {
    // Only show flights that are actually airborne (have a computable position)
    const airborne = activeFlights.filter((f) =>
      ["departed", "airborne", "approach"].includes(f.status),
    );
    if (!searchPlane) return airborne;
    const query = searchPlane.toLowerCase();
    return airborne.filter(
      (f) =>
        f.flight_number.toLowerCase().includes(query) ||
        f.airline_code.toLowerCase().includes(query) ||
        f.destination_iata.toLowerCase().includes(query) ||
        f.origin_iata.toLowerCase().includes(query),
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

    // Compute position using current sim time
    const currentSimTime = timelineActive
      ? (() => {
          const base = new Date(simTime);
          base.setMinutes(base.getMinutes() + timelineOffset);
          return base.toISOString();
        })()
      : simTime;

    // Fly to the plane's current position with a close zoom
    const pos = computeAircraftPosition(flight, currentSimTime);
    if (pos && mapRef.current) {
      if (hasMapboxToken) {
        (mapRef.current as { flyTo?: (options: unknown) => void }).flyTo?.({
          center: [pos.lon, pos.lat],
          zoom: 7,
          duration: 1800,
          pitch: 45,
        });
      } else {
        (
          mapRef.current as {
            flyTo?: (latLng: unknown, zoom: number, options?: unknown) => void;
          }
        ).flyTo?.([pos.lat, pos.lon], 7, { duration: 1.8 });
      }
    }
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

  // Effective sim time: live or overridden by timeline cursor
  const effectiveSimTime = useMemo(() => {
    if (!timelineActive) return simTime;
    const base = new Date(simTime);
    base.setMinutes(base.getMinutes() + timelineOffset);
    return base.toISOString();
  }, [simTime, timelineActive, timelineOffset]);

  const positionFeatures = useMemo(
    () =>
      activeFlights
        .map((flight) => toPositionFeature(flight, effectiveSimTime))
        .filter((feature): feature is PositionFeature => Boolean(feature)),
    [activeFlights, effectiveSimTime],
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
      // For departures show destination, for arrivals show origin
      const iata =
        flight.direction === "arrival"
          ? flight.origin_iata
          : flight.destination_iata;
      if (seen.has(iata)) {
        continue;
      }
      const coords = destinationCoordinates(iata);
      if (!coords) {
        continue;
      }
      seen.add(iata);
      features.push({
        type: "Feature",
        geometry: {
          type: "Point",
          coordinates: [coords.lon, coords.lat],
        },
        properties: {
          iata,
          name: `Airport ${iata}`,
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
    return findMatchingAdsb(
      selectedFlight,
      effectiveSimTime,
      adsbData.features,
    );
  }, [showAdsb, selectedFlight, adsbData, effectiveSimTime]);

  useEffect(() => {
    if (!mapContainerRef.current) {
      return;
    }

    if (hasMapboxToken) {
      let disposed = false;
      void (async () => {
        let mapboxgl;
        try {
          mapboxgl = (await import("mapbox-gl")).default;
        } catch (err) {
          console.warn(
            "[WorldMap] Failed to load mapbox-gl, falling back to Leaflet:",
            err,
          );
          setMapboxFailed(true);
          return;
        }
        if (disposed || !mapContainerRef.current) return;
        mapboxgl.accessToken = token as string;

        let map: InstanceType<typeof mapboxgl.Map>;
        try {
          map = new mapboxgl.Map({
            container: mapContainerRef.current as HTMLElement,
            style: "mapbox://styles/mapbox/satellite-streets-v12",
            center: [KART_COORDINATES.lon, KART_COORDINATES.lat],
            zoom: 3,
            pitch: 34,
            antialias: true,
          });
        } catch (err) {
          console.warn(
            "[WorldMap] Mapbox constructor failed, falling back to Leaflet:",
            err,
          );
          setMapboxFailed(true);
          return;
        }

        // Fall back to Leaflet on ANY Mapbox error (token, style, WebGL, network, etc.)
        map.on("error", (e) => {
          if (disposed) return;
          const msg = String(e?.error?.message ?? e?.error ?? "");
          console.warn(
            "[WorldMap] Mapbox error, falling back to Leaflet:",
            msg,
          );
          map.remove();
          mapRef.current = null;
          setMapboxFailed(true);
        });

        // Timeout fallback: if the map hasn't loaded after 10s, switch to Leaflet
        const loadTimeout = setTimeout(() => {
          if (disposed || !mapRef.current) return;
          if (!(map as unknown as { loaded: () => boolean }).loaded?.()) {
            console.warn(
              "[WorldMap] Mapbox load timeout, falling back to Leaflet",
            );
            map.remove();
            mapRef.current = null;
            setMapboxFailed(true);
          }
        }, 10_000);

        mapRef.current = map;
        map.addControl(
          new mapboxgl.NavigationControl({ showCompass: true }),
          "top-right",
        );

        map.on("load", () => {
          clearTimeout(loadTimeout);
          if (disposed) {
            return;
          }

          // Ensure the canvas matches the (now correctly-sized) container
          map.resize();

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
          map.addSource("network-arcs", {
            type: "geojson",
            data: EMPTY_FEATURE_COLLECTION,
          });
          map.addSource("network-airports", {
            type: "geojson",
            data: EMPTY_FEATURE_COLLECTION,
          });

          map.addLayer({
            id: "routes-line",
            type: "line",
            source: "routes",
            paint: {
              "line-color": [
                "case",
                ["==", ["get", "direction"], "arrival"],
                "#34d399",
                "#22d3ee",
              ],
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

          // ── Network overlay layers ──
          map.addLayer({
            id: "network-arcs-line",
            type: "line",
            source: "network-arcs",
            paint: {
              "line-color": [
                "case",
                ["==", ["get", "status"], "red"],
                "#ef4444",
                ["==", ["get", "status"], "amber"],
                "#f59e0b",
                "#10b981",
              ],
              "line-width": ["interpolate", ["linear"], ["zoom"], 2, 2, 8, 4],
              "line-opacity": 0.8,
            },
            layout: { visibility: "none" },
          });

          map.addLayer({
            id: "network-airports-circles",
            type: "circle",
            source: "network-airports",
            paint: {
              "circle-color": [
                "case",
                ["==", ["get", "is_home"], 1],
                "#fbbf24",
                ["==", ["get", "disruption_level"], "red"],
                "#ef4444",
                ["==", ["get", "disruption_level"], "amber"],
                "#f59e0b",
                "#10b981",
              ],
              "circle-stroke-color": "#0f172a",
              "circle-stroke-width": 2,
              "circle-radius": [
                "interpolate",
                ["linear"],
                ["zoom"],
                2,
                5,
                8,
                8,
              ],
            },
            layout: { visibility: "none" },
          });

          map.addLayer({
            id: "network-airports-labels",
            type: "symbol",
            source: "network-airports",
            layout: {
              "text-field": ["get", "iata"],
              "text-size": 12,
              "text-offset": [0, 1.4],
              "text-allow-overlap": true,
              "text-font": ["DIN Pro Bold", "Arial Unicode MS Bold"],
              visibility: "none",
            },
            paint: {
              "text-color": "#f0fdf4",
              "text-halo-color": "#0f172a",
              "text-halo-width": 1.5,
            },
          });

          // Click network airport to fly there
          map.on(
            "click",
            "network-airports-circles",
            (event: { lngLat?: { lng: number; lat: number } }) => {
              const lngLat = event.lngLat;
              if (lngLat) {
                map.flyTo({
                  center: [lngLat.lng, lngLat.lat],
                  zoom: 6,
                  duration: 1500,
                });
              }
            },
          );
          map.on("mouseenter", "network-airports-circles", () => {
            map.getCanvas().style.cursor = "pointer";
          });
          map.on("mouseleave", "network-airports-circles", () => {
            map.getCanvas().style.cursor = "";
          });

          // Use inline SVG data URLs for stable icon rendering.
          // Departure: cyan (#22d3ee), Arrival: green (#34d399), Selected: yellow (#facc15)
          const planeSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
            <path d="M24 4 L29 18 L44 22 L29 26 L26 44 L24 40 L22 44 L19 26 L4 22 L19 18 Z"
                  fill="#22d3ee" stroke="#0a2a33" stroke-width="1.5" stroke-linejoin="round"/>
          </svg>`;
          const arrivalPlaneSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
            <path d="M24 4 L29 18 L44 22 L29 26 L26 44 L24 40 L22 44 L19 26 L4 22 L19 18 Z"
                  fill="#34d399" stroke="#0a2a33" stroke-width="1.5" stroke-linejoin="round"/>
          </svg>`;
          const selectedPlaneSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
            <path d="M24 4 L29 18 L44 22 L29 26 L26 44 L24 40 L22 44 L19 26 L4 22 L19 18 Z"
                  fill="#facc15" stroke="#0a2a33" stroke-width="1.5" stroke-linejoin="round"/>
          </svg>`;
          const planeSvgUrl =
            "data:image/svg+xml;charset=utf-8," + encodeURIComponent(planeSvg);
          const arrivalPlaneSvgUrl =
            "data:image/svg+xml;charset=utf-8," +
            encodeURIComponent(arrivalPlaneSvg);
          const selectedPlaneSvgUrl =
            "data:image/svg+xml;charset=utf-8," +
            encodeURIComponent(selectedPlaneSvg);

          const planeImg = new Image(48, 48);
          planeImg.onload = () => {
            if (map.hasImage("plane-icon")) map.removeImage("plane-icon");
            map.addImage("plane-icon", planeImg);

            const arrivalPlaneImg = new Image(48, 48);
            arrivalPlaneImg.onload = () => {
              if (map.hasImage("plane-icon-arrival"))
                map.removeImage("plane-icon-arrival");
              map.addImage("plane-icon-arrival", arrivalPlaneImg);

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
                      ["==", ["get", "direction"], "arrival"],
                      "plane-icon-arrival",
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
                  const flightId = event.features?.[0]?.properties
                    ?.flight_id as string | undefined;
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
                      visibility: "none",
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
                      const alt =
                        props.altitude_m != null
                          ? `${Math.round(Number(props.altitude_m))}m`
                          : "—";
                      const speed =
                        props.velocity_ms != null
                          ? `${Math.round(Number(props.velocity_ms) * 1.944)}kt`
                          : "—";
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
            arrivalPlaneImg.src = arrivalPlaneSvgUrl;
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
        setPaintProperty?: (
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
          ["==", ["get", "direction"], "arrival"],
          "plane-icon-arrival",
          "plane-icon",
        ]);
      }

      // Highlight selected flight's route; arrivals are green, departures cyan
      if (map.isStyleLoaded?.() && map.getLayer?.("routes-line")) {
        map.setPaintProperty?.("routes-line", "line-color", [
          "case",
          ["==", ["get", "flight_id"], selectedFlightId ?? ""],
          "#facc15",
          ["==", ["get", "direction"], "arrival"],
          "#34d399",
          "#22d3ee",
        ]);
        map.setPaintProperty?.("routes-line", "line-opacity", [
          "case",
          ["==", ["get", "flight_id"], selectedFlightId ?? ""],
          1,
          0.45,
        ]);
      }

      // Update network overlay
      const networkVis = showNetwork ? "visible" : "none";
      if (map.isStyleLoaded?.()) {
        for (const layerId of [
          "network-arcs-line",
          "network-airports-circles",
          "network-airports-labels",
        ]) {
          if (map.getLayer?.(layerId)) {
            map.setLayoutProperty?.(layerId, "visibility", networkVis);
          }
        }
      }
      if (showNetwork && networkData) {
        const arcFeatures = (networkData.arcs ?? []).map((arc: NetworkArc) => ({
          type: "Feature" as const,
          geometry: {
            type: "LineString" as const,
            coordinates: [
              [arc.source.lon, arc.source.lat],
              [arc.target.lon, arc.target.lat],
            ],
          },
          properties: {
            source_iata: arc.source.iata,
            target_iata: arc.target.iata,
            status: arc.status,
            outbound_delay: arc.outbound_delay_minutes,
            inbound_delay: arc.inbound_delay_minutes,
          },
        }));
        map
          .getSource("network-arcs")
          ?.setData?.({ type: "FeatureCollection", features: arcFeatures });

        const netAirportFeatures = networkData.airports.map((a) => ({
          type: "Feature" as const,
          geometry: { type: "Point" as const, coordinates: [a.lon, a.lat] },
          properties: {
            iata: a.iata,
            icao: a.icao,
            name: a.name,
            is_home: a.icao === networkData.home ? 1 : 0,
            disruption_level: a.disruption_level,
            delay_minutes: a.current_delay_minutes,
          },
        }));
        map.getSource("network-airports")?.setData?.({
          type: "FeatureCollection",
          features: netAirportFeatures,
        });
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
        const isSelected = route.properties.flight_id === selectedFlightId;
        const latlngs = route.geometry.coordinates.map(
          (coord) => [coord[1], coord[0]] as [number, number],
        );
        const routeColor = isSelected
          ? "#facc15"
          : route.properties.direction === "arrival"
            ? "#34d399"
            : "#66d3ff";
        const line = L.polyline(latlngs, {
          color: routeColor,
          dashArray: isSelected ? undefined : "6, 8",
          opacity: isSelected ? 1 : 0.55,
          weight: isSelected ? 3 : 2,
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
        const fill = isSelected
          ? "#facc15"
          : feature.properties.direction === "arrival"
            ? "#34d399"
            : "#22d3ee";
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
    showNetwork,
    networkData,
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
              {new Date(effectiveSimTime).toISOString()}
              {timelineActive && (
                <span className="text-amber-400 ml-1">(timeline)</span>
              )}
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
              📡 ADS-B{" "}
              {showAdsb && adsbData
                ? `(${adsbData.metadata.aircraft_count})`
                : ""}
            </button>
            <button
              type="button"
              onClick={() => setShowNetwork(!showNetwork)}
              className={`px-3 py-1 rounded transition-colors font-medium ${
                showNetwork
                  ? "bg-emerald-600 hover:bg-emerald-700 text-white"
                  : "bg-slate-700 hover:bg-slate-600 text-slate-300"
              }`}
              title="Toggle multi-airport network overlay"
            >
              🌐 Network{" "}
              {showNetwork && networkData
                ? `(${networkData.airports.length})`
                : ""}
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
        {/* Wrapper keeps absolute positioning even after Mapbox injects
            position:relative via .mapboxgl-map on the inner div. */}
        <div className="absolute inset-0">
          <div ref={mapContainerRef} className="w-full h-full" />
        </div>

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
                  <span className="flex items-center gap-1">
                    <span className="inline-block w-2 h-2 rounded-full bg-cyan-400" />
                    Departures:
                  </span>
                  <span className="font-semibold text-slate-200">
                    {
                      activeFlights.filter((f) => f.direction === "departure")
                        .length
                    }
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="flex items-center gap-1">
                    <span className="inline-block w-2 h-2 rounded-full bg-emerald-400" />
                    Arrivals:
                  </span>
                  <span className="font-semibold text-slate-200">
                    {
                      activeFlights.filter((f) => f.direction === "arrival")
                        .length
                    }
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
            {showAdsb &&
              !trackComparison &&
              selectedFlight.status === "airborne" && (
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

      {/* Timeline Cursor */}
      <div className="px-4 py-1.5 border-t border-slate-800 bg-slate-900/95 flex items-center gap-3 text-xs">
        <button
          type="button"
          onClick={() => {
            setTimelineActive(!timelineActive);
            setTimelineOffset(0);
          }}
          className={`px-2 py-1 rounded font-medium transition-colors ${
            timelineActive
              ? "bg-amber-600 hover:bg-amber-700 text-white"
              : "bg-slate-700 hover:bg-slate-600 text-slate-300"
          }`}
          title="Toggle timeline scrubber"
        >
          🕐 Timeline
        </button>
        {timelineActive && (
          <>
            <input
              type="range"
              min={-360}
              max={360}
              value={timelineOffset}
              onChange={(e) => setTimelineOffset(Number(e.target.value))}
              className="flex-1 accent-amber-500 h-1.5"
            />
            <span className="text-slate-300 font-mono w-16 text-right">
              {timelineOffset >= 0 ? "+" : ""}
              {timelineOffset}m
            </span>
            <button
              type="button"
              onClick={() => setTimelineOffset(0)}
              className="text-slate-400 hover:text-white px-1.5 py-0.5 rounded bg-slate-700 hover:bg-slate-600"
            >
              Reset
            </button>
          </>
        )}
        {showAdsb && (
          <span className="ml-auto text-slate-500">
            <span className="inline-block w-2 h-2 rounded-full bg-cyan-400 mr-1" />
            Simulated
            <span className="inline-block w-2 h-2 rounded-full bg-orange-400 ml-2 mr-1" />
            Real (ADS-B)
          </span>
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
        {showNetwork && networkData && (
          <div className="bg-emerald-900/50 rounded px-2 py-1 text-emerald-200">
            NET: {networkData.airports.length} airports
          </div>
        )}
      </footer>

      {/* Network status panel */}
      {showNetwork && networkData && (
        <NetworkPanel
          data={networkData}
          onFlyToAirport={(lat, lon) => {
            if (!mapRef.current) return;
            if (hasMapboxToken) {
              const map = mapRef.current as { flyTo?: (opts: unknown) => void };
              map.flyTo?.({ center: [lon, lat], zoom: 6, duration: 1500 });
            } else {
              const map = mapRef.current as {
                flyTo?: (latLng: unknown, zoom: number, opts?: unknown) => void;
              };
              map.flyTo?.([lat, lon], 6, { duration: 1.5 });
            }
          }}
        />
      )}
    </section>
  );
}

/* ──────── Network Panel ──────── */
function NetworkPanel({
  data,
  onFlyToAirport,
}: {
  data: NetworkStatus;
  onFlyToAirport: (lat: number, lon: number) => void;
}) {
  const statusColor = (level: string) => {
    switch (level) {
      case "red":
        return "text-red-400";
      case "amber":
        return "text-amber-400";
      default:
        return "text-green-400";
    }
  };

  const statusBg = (level: string) => {
    switch (level) {
      case "red":
        return "bg-red-900/30 border-red-700/50";
      case "amber":
        return "bg-amber-900/30 border-amber-700/50";
      default:
        return "bg-slate-800/50 border-slate-700/50";
    }
  };

  return (
    <aside className="absolute bottom-16 left-3 w-80 rounded border border-emerald-700/50 bg-slate-950/96 text-xs shadow-lg backdrop-blur-sm p-3 max-h-80 overflow-y-auto">
      <h2 className="text-sm font-semibold text-emerald-300 mb-2">
        🌐 {data.name}
      </h2>

      {/* Airport status cards */}
      <div className="space-y-1.5">
        {data.airports.map((airport) => (
          <div
            key={airport.icao}
            className={`rounded border p-2 cursor-pointer hover:brightness-125 transition-all ${statusBg(airport.disruption_level)}`}
            onClick={() => onFlyToAirport(airport.lat, airport.lon)}
            title={`Click to fly to ${airport.iata}`}
          >
            <div className="flex items-center justify-between">
              <div>
                <span className="font-bold text-slate-100">{airport.iata}</span>
                <span className="text-slate-400 ml-1.5">{airport.name}</span>
              </div>
              <span
                className={`font-bold uppercase text-[10px] ${statusColor(airport.disruption_level)}`}
              >
                {airport.disruption_level}
              </span>
            </div>
            <div className="flex items-center gap-3 mt-1 text-slate-400">
              <span>Delay: {airport.current_delay_minutes} min</span>
              {airport.gdp_active && (
                <span className="text-red-400 font-bold">GDP ACTIVE</span>
              )}
              {airport.recovery_eta_minutes > 0 && (
                <span>
                  Recovery: ~{Math.ceil(airport.recovery_eta_minutes)} min
                </span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Active GDPs */}
      {data.active_gdps.length > 0 && (
        <div className="mt-3 pt-2 border-t border-slate-700">
          <h3 className="text-[10px] uppercase tracking-wide text-red-400 font-bold mb-1">
            Active Ground Delay Programs
          </h3>
          {data.active_gdps.map((gdp) => (
            <div key={gdp.airport_icao} className="text-slate-300 mb-1">
              <span className="font-bold">{gdp.airport_icao}</span>:{" "}
              {gdp.reason}
              <br />
              <span className="text-slate-400">
                Departure rate: {Math.round(gdp.departure_rate_pct * 100)}% —
                Feeders: {gdp.affected_feeder_airports.join(", ")}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Recent propagations */}
      {data.recent_propagations.length > 0 && (
        <div className="mt-3 pt-2 border-t border-slate-700">
          <h3 className="text-[10px] uppercase tracking-wide text-emerald-400 font-bold mb-1">
            Recent Delay Propagations
          </h3>
          {data.recent_propagations
            .slice(-5)
            .reverse()
            .map((p, i) => (
              <div key={i} className="text-slate-400 mb-0.5">
                {p.flight_number}: {p.source_icao} → {p.target_icao} (
                {p.propagated_delay_minutes} min)
              </div>
            ))}
        </div>
      )}
    </aside>
  );
}
