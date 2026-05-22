export interface PositionFeature {
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

export interface RouteFeature {
  type: "Feature";
  geometry: { type: "LineString"; coordinates: [number, number][] };
  properties: {
    flight_id: string;
    flight_number: string;
    destination_iata: string;
    direction: string;
  };
}

export interface AirportFeature {
  type: "Feature";
  geometry: { type: "Point"; coordinates: [number, number] };
  properties: {
    iata: string;
    name: string;
    is_home: number;
  };
}

export const EMPTY_FEATURE_COLLECTION = {
  type: "FeatureCollection" as const,
  features: [],
};

export const MAPBOX_STYLES: Record<string, string> = {
  satellite: "mapbox://styles/mapbox/satellite-streets-v12",
  dark: "mapbox://styles/mapbox/dark-v11",
  streets: "mapbox://styles/mapbox/streets-v12",
};
