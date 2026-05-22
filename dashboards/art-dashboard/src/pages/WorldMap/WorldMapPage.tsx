import { useEffect, useMemo, useRef, useState } from "react";
import "mapbox-gl/dist/mapbox-gl.css";
import "leaflet/dist/leaflet.css";
import {
  useFlightBoardQueries,
  useADSBQuery,
  useNetworkStatusQuery,
} from "../../hooks/useQueries";
import { useSimStore } from "../../stores/simStore";
import { useWorldMapSettingsStore } from "../../stores/worldMapSettingsStore";
import type { Flight, ADSBFeatureCollection } from "../../types";
import type { NetworkStatus, NetworkArc } from "../../hooks/useApi";
import {
  KART_COORDINATES,
  computeAircraftPosition,
  destinationCoordinates,
} from "../../utils/geospatial";
import { MapControlPanel } from "../../components/MapControlPanel";
import type { PositionFeature, RouteFeature, AirportFeature } from "./types";
import { EMPTY_FEATURE_COLLECTION, MAPBOX_STYLES } from "./types";
import { findMatchingAdsb, toPositionFeature, toRouteFeature } from "./helpers";
import { NetworkPanel } from "./NetworkPanel";

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
  // Persistent UI settings (stored in localStorage so toggles survive reloads)
  const showSearchPanel = useWorldMapSettingsStore((s) => s.showSearchPanel);
  const setShowSearchPanel = useWorldMapSettingsStore(
    (s) => s.setShowSearchPanel,
  );
  const showControlPanel = useWorldMapSettingsStore((s) => s.showControlPanel);
  const setShowControlPanel = useWorldMapSettingsStore(
    (s) => s.setShowControlPanel,
  );
  const showAdsb = useWorldMapSettingsStore((s) => s.showAdsb);
  const showNetwork = useWorldMapSettingsStore((s) => s.showNetwork);
  const showRoutes = useWorldMapSettingsStore((s) => s.showRoutes);
  const flightFilter = useWorldMapSettingsStore((s) => s.flightFilter);
  const statusFilter = useWorldMapSettingsStore((s) => s.statusFilter);
  const mapStyle = useWorldMapSettingsStore((s) => s.mapStyle);
  const [timelineActive, setTimelineActive] = useState(false);
  const [timelineOffset, setTimelineOffset] = useState(0); // minutes offset from sim start
  const [selectedAdsbInfo, setSelectedAdsbInfo] = useState<{
    callsign: string;
    altitude: string;
    speed: string;
    distance: string;
    country: string;
    icao24: string;
    heading: string;
  } | null>(null);

  const adsbQuery = useADSBQuery(showAdsb);
  const adsbData = adsbQuery.data as ADSBFeatureCollection | undefined;

  // Ref so map-init closure can read current showAdsb state
  const showAdsbRef = useRef(showAdsb);
  showAdsbRef.current = showAdsb;
  const adsbDataRef = useRef(adsbData);
  adsbDataRef.current = adsbData;
  const mapStyleRef = useRef(mapStyle);
  mapStyleRef.current = mapStyle;
  const [mapLoaded, setMapLoaded] = useState(false);

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
    let airborne = activeFlights.filter((f) =>
      ["departed", "airborne", "approach"].includes(f.status),
    );
    // Apply direction filter
    if (flightFilter === "departures") {
      airborne = airborne.filter((f) => f.direction === "departure");
    } else if (flightFilter === "arrivals") {
      airborne = airborne.filter((f) => f.direction === "arrival");
    }
    // Apply status filter
    if (statusFilter === "airborne") {
      airborne = airborne.filter((f) =>
        ["airborne", "departed"].includes(f.status),
      );
    } else if (statusFilter === "boarding") {
      airborne = airborne.filter((f) => f.status === "boarding");
    } else if (statusFilter === "ground") {
      airborne = airborne.filter((f) =>
        ["approach", "landed", "taxiing"].includes(f.status),
      );
    }
    if (!searchPlane) return airborne;
    const query = searchPlane.toLowerCase();
    return airborne.filter(
      (f) =>
        f.flight_number.toLowerCase().includes(query) ||
        f.airline_code.toLowerCase().includes(query) ||
        f.destination_iata.toLowerCase().includes(query) ||
        f.origin_iata.toLowerCase().includes(query),
    );
  }, [activeFlights, searchPlane, flightFilter, statusFilter]);

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

  const selectPlane = (
    flightId: string,
    clickCoords?: { lon: number; lat: number } | null,
  ) => {
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

    // Prefer the clicked coordinates (exact icon position on map) over
    // recomputed position which may have drifted to the destination for
    // flights near fraction ≈ 1.
    const pos = clickCoords ?? computeAircraftPosition(flight, currentSimTime);
    if (pos && mapRef.current) {
      if (hasMapboxToken) {
        (mapRef.current as { flyTo?: (options: unknown) => void }).flyTo?.({
          center: [pos.lon, pos.lat],
          zoom: 10,
          duration: 1800,
          pitch: 45,
        });
      } else {
        (
          mapRef.current as {
            flyTo?: (latLng: unknown, zoom: number, options?: unknown) => void;
          }
        ).flyTo?.([pos.lat, pos.lon], 10, { duration: 1.8 });
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

  const positionFeatures = useMemo(() => {
    let flights = activeFlights;
    if (flightFilter === "departures")
      flights = flights.filter((f) => f.direction === "departure");
    else if (flightFilter === "arrivals")
      flights = flights.filter((f) => f.direction === "arrival");
    return flights
      .map((flight) => toPositionFeature(flight, effectiveSimTime))
      .filter((feature): feature is PositionFeature => Boolean(feature));
  }, [activeFlights, effectiveSimTime, flightFilter]);

  const routeFeatures = useMemo(() => {
    if (!showRoutes) return [];
    let flights = activeFlights;
    if (flightFilter === "departures")
      flights = flights.filter((f) => f.direction === "departure");
    else if (flightFilter === "arrivals")
      flights = flights.filter((f) => f.direction === "arrival");
    return flights
      .map((flight) => toRouteFeature(flight))
      .filter((feature): feature is RouteFeature => Boolean(feature));
  }, [activeFlights, showRoutes, flightFilter]);

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
            style:
              MAPBOX_STYLES[mapStyleRef.current] ?? MAPBOX_STYLES.satellite,
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
          // Departure: cyan (#22d3ee), Arrival: green (#34d399),
          // Selected: yellow (#facc15), ADS-B: orange (#f97316).
          const ICON_SVGS: Record<string, string> = {
            "plane-icon": "#22d3ee",
            "plane-icon-arrival": "#34d399",
            "plane-icon-selected": "#facc15",
            "adsb-icon": "#f97316",
          };

          const loadImage = (name: string, color: string): Promise<void> => {
            const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48"><path d="M24 4 L29 18 L44 22 L29 26 L26 44 L24 40 L22 44 L19 26 L4 22 L19 18 Z" fill="${color}" stroke="#0a2a33" stroke-width="1.5" stroke-linejoin="round"/></svg>`;
            const url =
              "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
            return new Promise((resolve, reject) => {
              const img = new Image(48, 48);
              img.onload = () => {
                if (map.hasImage(name)) map.removeImage(name);
                map.addImage(name, img);
                resolve();
              };
              img.onerror = () =>
                reject(new Error(`Failed to load icon: ${name}`));
              img.src = url;
            });
          };

          Promise.all(
            Object.entries(ICON_SVGS).map(([name, color]) =>
              loadImage(name, color),
            ),
          )
            .then(() => {
              if (disposed) return;

              // Both layers are created with visibility: "visible". To hide the
              // ADS-B layer we simply push an empty FeatureCollection to its
              // source — this avoids the historical race where setLayoutProperty
              // would silently no-op while the style was still settling.
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
                const flightId = event.features?.[0]?.properties?.flight_id as
                  | string
                  | undefined;
                if (flightId) {
                  // Use the clicked coordinates so the camera flies to
                  // the actual icon position, not a recomputed one that
                  // may have drifted to the destination airport.
                  const clickCoords = event.lngLat
                    ? { lon: event.lngLat.lng, lat: event.lngLat.lat }
                    : null;
                  selectPlane(flightId, clickCoords);
                }
              });
              map.on("mouseenter", "aircraft-symbols", () => {
                map.getCanvas().style.cursor = "pointer";
              });
              map.on("mouseleave", "aircraft-symbols", () => {
                map.getCanvas().style.cursor = "";
              });

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
                  // Only show callsign labels when zoomed in enough to
                  // avoid cluttering the map with thousands of labels.
                  "text-field": [
                    "step",
                    ["zoom"],
                    "", // hidden below zoom 9
                    9,
                    ["get", "callsign"],
                  ],
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
                  visibility: "visible",
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
                      ? `${Math.round(Number(props.altitude_m))}m (FL${Math.round((Number(props.altitude_m) * 3.28084) / 100)})`
                      : "—";
                  const speed =
                    props.velocity_ms != null
                      ? `${Math.round(Number(props.velocity_ms) * 1.944)}kt`
                      : "—";
                  const dist = `${Number(props.distance_km).toFixed(0)}km`;
                  const hdg =
                    props.heading != null
                      ? `${Math.round(Number(props.heading))}°`
                      : "—";
                  setSelectedAdsbInfo({
                    callsign,
                    altitude: alt,
                    speed,
                    distance: dist,
                    country: String(props.origin_country ?? ""),
                    icao24: String(props.icao24 ?? ""),
                    heading: hdg,
                  });
                  // Fly to the clicked ADS-B aircraft
                  if (event.lngLat) {
                    map.flyTo({
                      center: [event.lngLat.lng, event.lngLat.lat],
                      zoom: Math.max(map.getZoom(), 8),
                      duration: 1200,
                    });
                  }
                }
              });
              map.on("mouseenter", "adsb-symbols", () => {
                map.getCanvas().style.cursor = "pointer";
              });
              map.on("mouseleave", "adsb-symbols", () => {
                map.getCanvas().style.cursor = "";
              });

              // Seed any pending ADS-B data captured before the layer existed.
              const currentAdsb = adsbDataRef.current;
              if (showAdsbRef.current && currentAdsb?.features) {
                (
                  map.getSource("adsb-aircraft") as
                    | { setData?: (data: unknown) => void }
                    | undefined
                )?.setData?.({
                  type: "FeatureCollection",
                  features: currentAdsb.features.filter(
                    (f) => !f.properties.on_ground,
                  ),
                });
              }

              // Signal that all layers are ready so the data-update effect
              // re-runs and pushes any state that was waiting in refs.
              setMapLoaded(true);
            })
            .catch((err) => {
              console.warn(
                "[WorldMap] Failed to load aircraft icons; map will render without symbols:",
                err,
              );
              setMapLoaded(true);
            });

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
        setMapLoaded(false);
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
  }, [hasMapboxToken, token, mapStyle]);

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

      // Update ADS-B source. Layer visibility is fixed at "visible"; we hide
      // ADS-B by feeding an empty FeatureCollection. This avoids the historical
      // race where setLayoutProperty silently no-op'd while the style settled.
      // Also filter out on_ground aircraft so only airborne real flights appear.
      const adsbFeatures =
        showAdsb && adsbData?.features
          ? adsbData.features.filter((f) => !f.properties.on_ground)
          : [];
      map.getSource("adsb-aircraft")?.setData?.({
        type: "FeatureCollection" as const,
        features: adsbFeatures,
      });

      if (map.getLayer?.("aircraft-symbols")) {
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
      if (map.getLayer?.("routes-line")) {
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
      for (const layerId of [
        "network-arcs-line",
        "network-airports-circles",
        "network-airports-labels",
      ]) {
        if (map.getLayer?.(layerId)) {
          map.setLayoutProperty?.(layerId, "visibility", networkVis);
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

      // Leaflet: ADS-B aircraft markers (orange, smaller)
      if (showAdsb && adsbData?.features) {
        for (const f of adsbData.features) {
          if (f.properties.on_ground) continue;
          const [lon, lat] = f.geometry.coordinates;
          const heading = f.properties.heading ?? 0;
          const icon = L.divIcon({
            className: "",
            iconSize: [22, 22],
            iconAnchor: [11, 11],
            html: `<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 48 48"
                        style="transform:rotate(${heading}deg)">
                     <path d="M24 4 L29 18 L44 22 L29 26 L26 44 L24 40 L22 44 L19 26 L4 22 L19 18 Z"
                           fill="#f97316" stroke="#0a2a33" stroke-width="1.5" stroke-linejoin="round"/>
                   </svg>`,
          });
          const callsign =
            (f.properties.callsign ?? "").trim() || f.properties.icao24;
          const marker = L.marker([lat, lon], { icon }).bindTooltip(
            `📡 ${callsign}`,
          );
          marker.addTo(map as never);
          aircraftMarkersRef.current.push(marker);
        }
      }
    })();
  }, [
    adsbData,
    airportFeatures,
    hasMapboxToken,
    mapLoaded,
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
                ? `Mapbox ${mapStyle} with real destination airports`
                : "Leaflet OpenStreetMap fallback"}
              {" | Sim Time "}
              {new Date(effectiveSimTime).toISOString()}
              {timelineActive && (
                <span className="text-amber-400 ml-1">(timeline)</span>
              )}
            </p>
          </div>
          <div className="text-xs text-slate-300 flex items-center gap-2 flex-wrap">
            <button
              type="button"
              onClick={() => setShowControlPanel(!showControlPanel)}
              className={`px-3 py-1 rounded transition-colors font-medium ${
                showControlPanel
                  ? "bg-slate-600 hover:bg-slate-500 text-white"
                  : "bg-slate-700 hover:bg-slate-600 text-slate-300"
              }`}
              title="Map settings"
            >
              ⚙ Settings
            </button>
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

        {/* Unified Control Panel */}
        {showControlPanel && !showSearchPanel && (
          <MapControlPanel
            hasMapboxToken={hasMapboxToken}
            adsbCount={adsbData?.metadata.aircraft_count}
            networkCount={networkData?.airports.length}
            onClose={() => setShowControlPanel(false)}
          />
        )}

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
                <span className="text-slate-400">Heading:</span>{" "}
                {selectedAdsbInfo.heading}
              </p>
              <p>
                <span className="text-slate-400">Distance to KART:</span>{" "}
                {selectedAdsbInfo.distance}
              </p>
            </div>
            <div className="mt-2 pt-2 border-t border-slate-700 text-[10px] text-slate-500">
              Live data from adsb.lol
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
            Departures
            <span className="inline-block w-2 h-2 rounded-full bg-emerald-400 ml-2 mr-1" />
            Arrivals
            <span className="inline-block w-2 h-2 rounded-full bg-orange-400 ml-2 mr-1" />
            Real (ADS-B)
          </span>
        )}
        {!showAdsb && (
          <span className="ml-auto text-slate-500">
            <span className="inline-block w-2 h-2 rounded-full bg-cyan-400 mr-1" />
            Departures
            <span className="inline-block w-2 h-2 rounded-full bg-emerald-400 ml-2 mr-1" />
            Arrivals
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
