import type { Flight } from "../types";
import { DESTINATION_COORDINATES } from "../data/destinationCoordinates";

export interface GeoPoint {
  lat: number;
  lon: number;
}

export interface AircraftPosition extends GeoPoint {
  flight_id: string;
  flight_number: string;
  destination_iata: string;
  heading_deg: number;
  altitude_ft: number;
  fraction: number;
}

export const KART_COORDINATES: GeoPoint = {
  lat: 38.75,
  lon: -27.0833,
};

const EARTH_RADIUS_KM = 6371;

const FALLBACK_DESTINATIONS: Record<string, GeoPoint> = {
  LHR: { lat: 51.47, lon: -0.4543 },
  JFK: { lat: 40.6413, lon: -73.7781 },
  GRU: { lat: -23.4356, lon: -46.4731 },
  CDG: { lat: 49.0097, lon: 2.5479 },
  NBO: { lat: -1.3192, lon: 36.9278 },
  LIS: { lat: 38.7742, lon: -9.1342 },
  MAD: { lat: 40.4719, lon: -3.5626 },
  BOS: { lat: 42.3656, lon: -71.0096 },
};

function toRadians(value: number): number {
  return (value * Math.PI) / 180;
}

function toDegrees(value: number): number {
  return (value * 180) / Math.PI;
}

export function haversineDistanceKm(start: GeoPoint, end: GeoPoint): number {
  const lat1 = toRadians(start.lat);
  const lat2 = toRadians(end.lat);
  const dLat = toRadians(end.lat - start.lat);
  const dLon = toRadians(end.lon - start.lon);

  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return EARTH_RADIUS_KM * c;
}

export function greatCirclePoint(
  start: GeoPoint,
  end: GeoPoint,
  fraction: number,
): GeoPoint {
  const f = Math.min(1, Math.max(0, fraction));

  const phi1 = toRadians(start.lat);
  const lambda1 = toRadians(start.lon);
  const phi2 = toRadians(end.lat);
  const lambda2 = toRadians(end.lon);

  const delta = 2 * Math.asin(
    Math.sqrt(
      Math.sin((phi2 - phi1) / 2) ** 2 +
        Math.cos(phi1) * Math.cos(phi2) * Math.sin((lambda2 - lambda1) / 2) ** 2,
    ),
  );

  if (delta === 0) {
    return start;
  }

  const a = Math.sin((1 - f) * delta) / Math.sin(delta);
  const b = Math.sin(f * delta) / Math.sin(delta);

  const x =
    a * Math.cos(phi1) * Math.cos(lambda1) +
    b * Math.cos(phi2) * Math.cos(lambda2);
  const y =
    a * Math.cos(phi1) * Math.sin(lambda1) +
    b * Math.cos(phi2) * Math.sin(lambda2);
  const z = a * Math.sin(phi1) + b * Math.sin(phi2);

  const lat = Math.atan2(z, Math.sqrt(x * x + y * y));
  const lon = Math.atan2(y, x);

  return {
    lat: toDegrees(lat),
    lon: toDegrees(lon),
  };
}

export function computeBearing(from: GeoPoint, to: GeoPoint): number {
  const phi1 = toRadians(from.lat);
  const phi2 = toRadians(to.lat);
  const lambda1 = toRadians(from.lon);
  const lambda2 = toRadians(to.lon);

  const y = Math.sin(lambda2 - lambda1) * Math.cos(phi2);
  const x =
    Math.cos(phi1) * Math.sin(phi2) -
    Math.sin(phi1) * Math.cos(phi2) * Math.cos(lambda2 - lambda1);

  return (toDegrees(Math.atan2(y, x)) + 360) % 360;
}

function cruiseAltitudeFt(aircraftType: string): number {
  if (/B77|A33|A35|B78|B74/i.test(aircraftType)) {
    return 39000;
  }
  if (/E19|DH8|AT7/i.test(aircraftType)) {
    return 29000;
  }
  return 35000;
}

export function computeAltitude(
  fraction: number,
  aircraftType: string,
  status: Flight["status"],
): number {
  if (status === "approach") {
    const descent = Math.max(0, Math.min(1, fraction));
    return Math.max(1500, Math.round((1 - descent) * 12000));
  }

  const cruise = cruiseAltitudeFt(aircraftType);
  if (fraction < 0.16) {
    return Math.round((fraction / 0.16) * cruise);
  }
  if (fraction > 0.82) {
    return Math.round(((1 - fraction) / (1 - 0.82)) * cruise);
  }
  return cruise;
}

function parseIsoDate(value: string | null): Date | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function destinationCoordinates(iata: string): GeoPoint | null {
  const key = iata.toUpperCase();
  const fromDataset = DESTINATION_COORDINATES[key];
  if (fromDataset) {
    return fromDataset;
  }
  return FALLBACK_DESTINATIONS[key] ?? null;
}

function estimateDurationMinutes(distanceKm: number, aircraftType: string): number {
  const speedKmh = /B77|A33|A35|B78|B74/i.test(aircraftType) ? 900 : 820;
  return Math.max(45, Math.round((distanceKm / speedKmh) * 60));
}

export function computeAircraftPosition(
  flight: Flight,
  simTimeIso: string,
): AircraftPosition | null {
  if (flight.direction !== "departure") {
    return null;
  }
  if (!["departed", "airborne", "approach"].includes(flight.status)) {
    return null;
  }

  const destination = destinationCoordinates(flight.destination_iata);
  if (!destination) {
    return null;
  }

  const simTime = parseIsoDate(simTimeIso);
  const departedAt =
    parseIsoDate(flight.actual_time) ?? parseIsoDate(flight.estimated_time) ?? null;

  if (!simTime || !departedAt) {
    return null;
  }

  const distanceKm = haversineDistanceKm(KART_COORDINATES, destination);
  const durationMin = estimateDurationMinutes(distanceKm, flight.aircraft_type);
  const elapsedMin = (simTime.getTime() - departedAt.getTime()) / 60000;
  const fraction = Math.max(0, Math.min(1, elapsedMin / durationMin));

  const point = greatCirclePoint(KART_COORDINATES, destination, fraction);
  const heading = computeBearing(point, destination);

  return {
    flight_id: flight.id,
    flight_number: flight.flight_number,
    destination_iata: flight.destination_iata,
    lat: point.lat,
    lon: point.lon,
    heading_deg: heading,
    altitude_ft: computeAltitude(fraction, flight.aircraft_type, flight.status),
    fraction,
  };
}
