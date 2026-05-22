import type { Flight, ADSBFeatureCollection } from "../../types";
import {
  KART_COORDINATES,
  computeAircraftPosition,
  destinationCoordinates,
} from "../../utils/geospatial";
import type { PositionFeature, RouteFeature } from "./types";

/** Match an ADS-B aircraft to a simulated flight by heading similarity and distance. */
export function findMatchingAdsb(
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

export function toPositionFeature(
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

export function toRouteFeature(flight: Flight): RouteFeature | null {
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
