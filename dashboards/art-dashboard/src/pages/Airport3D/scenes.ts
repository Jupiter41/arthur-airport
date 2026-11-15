import * as T from "three";
import { aircraft, box, cylinder, label, line, material, palette, vehicle } from "./primitives";
import { buildLayout, checkpoint, entities, flightPose, gridPoint, holdingOrder, QUALITY, representativeCount, terminalY, type Entity, type Point, type SceneData, type SceneOptions } from "./model";
import { approachPoint, HOLD_RADII, holdingFix, isAtDepot, runwayFor, vehiclePose, type RunwayGeometry } from "./kinematics";

export interface BuiltScene {
  root: T.Group;
  entities: Entity[];
  /** Advance every time-driven object to simulation time `seconds` (epoch s). */
  update: (seconds: number) => void;
  /** Current scene position of a selectable entity, or null when off-scene. */
  locate: (id: string) => T.Vector3 | null;
  representatives: number;
}
const fixedLocator = (items: Entity[]) => (id: string) => {
  const e = items.find(item => item.id === id);
  return e && e.positionAvailable !== false ? new T.Vector3(...e.position) : null;
};
const frac = (v: number) => v - Math.floor(v);
const statusColor = (status: string) => ["closed", "offline", "maintenance", "frozen"].includes(status) ? palette.red : ["occupied", "degraded"].includes(status) ? palette.amber : palette.cyan;
const tag = (root: T.Object3D, entity: Entity) => { root.userData.entityId = entity.id; };

function base(root: T.Group, width: number, depth: number) {
  box(root, [width, 0.8, depth], [0, -0.7, 0], 0x142636);
  const grid = new T.GridHelper(Math.max(width, depth), 24, 0x2c4557, 0x203747); grid.position.y = -0.25; root.add(grid);
}

export function buildAirport(data: SceneData, options: SceneOptions, seconds: number): BuiltScene {
  const root = new T.Group(); const items = entities(data, options, seconds);
  base(root, 240, 220);
  // Architecture is an original schematic; all vehicle coordinates use the owner grid.
  for (const [i, terminal] of ["A", "B", "C"].entries()) {
    const z = (terminalY(terminal) - 500) / 5;
    box(root, [178, 2.8, 8], [9, 1.4, z - 10], 0x38576b);
    box(root, [178, 0.35, 9], [9, 3, z - 10], 0x638797);
    box(root, [48, 7, 18], [-75, 3.5, z - 12], 0x29475c);
    box(root, [48, 0.5, 19], [-75, 7.2, z - 12], 0x7d9eaa);
    for (let x = -96; x < 95; x += 6) box(root, [3.9, 1.5, 0.15], [x, 1.9, z - 5.95], 0x67a9bc);
    label(root, `TERMINAL ${terminal}`, [-78, 12, z - 13], 31);
    box(root, [194, 0.12, 18], [0, -0.12, z + 9], 0x233b4c);
    const taxiZ = z + 25;
    box(root, [205, 0.15, 5], [0, 0, taxiZ], 0x324651);
    line(root, [[-102, 0.12, taxiZ], [102, 0.12, taxiZ]], 0xc0a658);
    label(root, `APRON ${terminal} · ${i + 1}`, [88, 2, taxiZ + 5], 20, "#90b2c4");
  }
  box(root, [6, 0.12, 174], [-105, -0.05, 0], 0x324651);
  for (const entity of items.filter(e => e.kind === "gate")) {
    const group = new T.Group(); group.position.set(...entity.position); tag(group, entity);
    box(group, [6, 0.1, 16], [0, 0, 8], 0x314654);
    line(group, [[0, 0.15, 1], [0, 0.15, 16]], statusColor(entity.status));
    box(group, [1.6, 1.2, 5], [-1.7, 1.7, -2.5], 0x94a5ad);
    cylinder(group, 0.6, 1.7, [-1.7, 0.7, -0.5], 0x536878);
    label(group, entity.id, [0, 4, -0.8], 6, entity.status === "occupied" ? "#ffc888" : "#b6d9e5");
    root.add(group);
  }
  const strips = new Map<string, Entity[]>();
  for (const entity of items.filter(e => e.kind === "runway")) {
    const key = entity.position.join(","); strips.set(key, [...(strips.get(key) ?? []), entity]);
  }
  for (const ends of strips.values()) {
    const entity = ends[0];
    const group = new T.Group(); group.position.set(...entity.position); tag(group, entity);
    box(group, [180, 0.2, 8], [0, 0, 0], 0x101a27);
    for (let x = -78; x <= 78; x += 12) box(group, [5, 0.03, 0.4], [x, 0.15, 0], palette.white);
    for (const x of [-83, 83]) for (let z = -2.8; z <= 2.8; z += 0.8) box(group, [4, 0.03, 0.35], [x, 0.15, z], palette.white);
    for (let x = -90; x <= 90; x += 9) for (const z of [-4.1, 4.1]) cylinder(group, 0.15, 0.2, [x, 0.2, z], statusColor(entity.status));
    label(group, `${ends.map(e => e.id).join(" / ")} · ${ends.map(e => e.status.toUpperCase()).join(" / ")}`, [0, 2, 7], 44);
    root.add(group);
  }
  // Aircraft: one model per flight the owner places on or near the airfield.
  // Visibility and pose come from the owner timeline at each frame.
  const layout = buildLayout(data); const holding = holdingOrder(data.flights);
  const flightModels: Array<{ object: T.Group; flight: SceneData["flights"][number] }> = [];
  for (const flight of data.flights) {
    if (!flightPose(flight, data, seconds, layout, holding) && !["approach", "landed", "taxiing", "departed", "airborne"].includes(flight.status)) continue;
    const model = aircraft(/330|350|380|747|777|787/.test(flight.aircraft_type));
    tag(model, items.find(e => e.id === flight.id)!); root.add(model); flightModels.push({ object: model, flight });
    label(model, flight.flight_number, [0, 5, 0], 11);
  }
  // Vehicles: every owner vehicle, moving along its owner trip segment.
  // Stationary vehicles sharing one owner position get illustrative slots.
  const vehicleModels = data.vehicles.filter(v => Number.isFinite(v.position_x) && Number.isFinite(v.position_y)).map(source => {
    const model = vehicle(source.type, source.status !== "available");
    tag(model, items.find(e => e.id === source.id)!); root.add(model);
    return { object: model, source };
  });
  const depotOrder = new Map(vehicleModels.map((v, i) => [v.source.id, i]));
  const typeSlot: Record<string, [number, number]> = { fuel_truck: [-14, 3], catering_truck: [12, -2], pushback_tug: [0, 14], baggage_loader: [10, 6], stairs: [-8, -4] };
  const placed = new Map<string, T.Vector3>();
  const update = (now: number) => {
    placed.clear();
    for (const { object, flight } of flightModels) {
      const pose = flightPose(flight, data, now, layout, holding);
      object.visible = pose !== null;
      if (!pose) continue;
      object.position.set(...gridPoint(pose.x, pose.y, pose.altitude)); object.rotation.y = pose.heading;
      placed.set(flight.id, object.position);
    }
    for (const { object, source } of vehicleModels) {
      const p = vehiclePose(source, now);
      let [x, , z] = gridPoint(p.x, p.y);
      if (!p.moving && source.status === "available" && isAtDepot(p.x, p.y)) {
        const i = depotOrder.get(source.id)!; x += (i % 8 - 3.5) * 3; z += Math.floor(i / 8) * 4.5 - 6; // illustrative depot parking
      } else if (!p.moving) {
        const [dx, dz] = typeSlot[source.type] ?? [6, 6]; x += dx / 5; z += 9 + dz / 5; // beside the aircraft stand
      }
      object.position.set(x, 0.6, z); object.rotation.y = p.moving ? p.heading : 0;
      placed.set(source.id, object.position);
    }
  };
  update(seconds);
  const locate = (id: string) => placed.get(id)?.clone() ?? fixedLocator(items)(id);
  // Tower and landside road are static architecture, not an ATC control system.
  cylinder(root, 2, 17, [-106, 8, 47], 0x516f80);
  box(root, [9, 4, 8], [-106, 18, 47], 0x5794aa);
  box(root, [10, 0.5, 9], [-106, 20.2, 47], 0x99bbc6);
  label(root, "KART / ART", [-106, 24, 47], 24);
  return { root, entities: items, representatives: flightModels.length, update, locate };
}

export function buildPassengers(data: SceneData, options: SceneOptions, seconds: number): BuiltScene {
  const root = new T.Group(); const items = entities(data, options, seconds); const state = checkpoint(data, options.terminal);
  base(root, 190, 190);
  // Open roof/cutaway permits queue inspection without hiding operational state.
  box(root, [110, 10, 1], [0, 4.5, -54], 0x314f62);
  box(root, [1, 5, 110], [-54, 2, 0], 0x294658);
  for (let x = -48; x <= 48; x += 12) box(root, [0.5, 8, 0.5], [x, 3.5, -45], palette.steel);
  label(root, `TERMINAL ${options.terminal} / SECURITY`, [0, 13, -47], 64);
  label(root, "LANDSIDE / QUEUE", [-26, 2, 44], 30, "#93b1c4");
  label(root, "AIRSIDE", [0, 3, -39], 25, "#8ce4ce");
  for (let i = 0; i < 5; i++) {
    box(root, [7, 2, 3], [-40 + i * 20, 1, 48], 0x3c5c73);
    box(root, [1.3, 0.8, 0.1], [-40 + i * 20, 2.8, 48], palette.cyan);
  }
  const zoneEntities = items.filter(e => e.kind === "passenger_zone");
  let zoneRepresentatives = 0;
  const queueBudget = zoneEntities.length ? Math.floor(QUALITY[options.quality].people * 0.6) : QUALITY[options.quality].people;
  const zoneBudget = Math.floor((QUALITY[options.quality].people - queueBudget) / Math.max(1, zoneEntities.length));
  for (const entity of zoneEntities) {
    const source = data.passengerZones!.find(z => z.zone_id === entity.id)!;
    const group = new T.Group(); group.position.set(...entity.position); tag(group, entity); root.add(group);
    box(group, [18, 0.1, 16], [0, -0.15, 0], 0x294354);
    label(group, `${entity.label} · ${source.density}`, [0, 6, 0], 23);
    const n = representativeCount(source.density, zoneBudget); zoneRepresentatives += n;
    const bodies = new T.InstancedMesh(new T.CapsuleGeometry(0.36, 0.7, 3, 6), material(palette.blue), n);
    const heads = new T.InstancedMesh(new T.SphereGeometry(0.29, 7, 5), material(0xd9b9a0), n);
    group.add(bodies, heads); const dummy = new T.Object3D();
    for (let i = 0; i < n; i++) {
      dummy.position.set((i % 8 - 3.5) * 1.6, 1, (Math.floor(i / 8) - Math.ceil(n / 8) / 2) * 1.6);
      dummy.updateMatrix(); bodies.setMatrixAt(i, dummy.matrix); dummy.position.y = 2; dummy.updateMatrix(); heads.setMatrixAt(i, dummy.matrix);
    }
    bodies.instanceMatrix.needsUpdate = true; heads.instanceMatrix.needsUpdate = true;
    bodies.computeBoundingSphere(); heads.computeBoundingSphere();
  }
  if (!state) {
    label(root, "CHECKPOINT DATA UNAVAILABLE", [0, 8, 0], 55, "#ffc888");
    return { root, entities: items, representatives: zoneRepresentatives, update: () => {}, locate: fixedLocator(items) };
  }
  const laneCount = state.lanes_open;
  const laneWidth = Math.min(12, 95 / laneCount);
  const group = new T.Group(); tag(group, items[0]); root.add(group);
  for (let i = 0; i < laneCount; i++) {
    const x = (i - (laneCount - 1) / 2) * laneWidth;
    const open = i < state.lanes_open; const color = state.frozen ? palette.red : open ? palette.green : 0x4c6373;
    box(group, [laneWidth - 1, 0.1, 15], [x, -0.08, -20], open ? 0x294b4b : 0x233342);
    box(group, [0.6, 5, 1], [x - laneWidth / 3, 2.5, -20], color);
    box(group, [0.6, 5, 1], [x + laneWidth / 3, 2.5, -20], color);
    box(group, [laneWidth * 2 / 3 + 0.6, 0.6, 1], [x, 5, -20], color);
    box(group, [laneWidth / 3, 2, 5], [x + laneWidth / 3 + 1, 1, -20], palette.steel);
    label(group, state.frozen ? "FROZEN" : `LANE ${i + 1}`, [x, 7, -20], Math.min(10, laneWidth + 1), "#89e8cf");
  }
  const count = representativeCount(state.queue_length, queueBudget);
  // Two instanced draw calls for the entire crowd.
  const bodies = new T.InstancedMesh(new T.CapsuleGeometry(0.36, 0.7, 3, 6), material(palette.cyan), count);
  const heads = new T.InstancedMesh(new T.SphereGeometry(0.29, 7, 5), material(0xd9b9a0), count);
  group.add(bodies, heads); bodies.frustumCulled = false; heads.frustumCulled = false;
  const dummy = new T.Object3D();
  for (let i = 0; i < count; i++) bodies.setColorAt(i, new T.Color([0x6bb9cc, 0x5882a9, 0xe0b577, 0xa6bbd3, 0x749c9a][i % 5]));
  // Stanchions make queue shape legible without pretending to be installed hardware.
  for (let row = 0; row < 5; row++) for (const x of [-45, 45]) {
    cylinder(group, 0.12, 1.3, [x, 0.65, -8 + row * 10], palette.steel);
    line(group, [[-45, 1.3, -8 + row * 10], [45, 1.3, -8 + row * 10]], 0x7396a9);
  }
  // Little's law: a figure joining the back reaches the lanes after exactly the
  // owner's reported wait, so the crowd advances at the observed processing rate.
  const cycleSeconds = state.wait_minutes * 60;
  const flowing = !state.frozen && state.lanes_open > 0 && cycleSeconds > 0 && count > 0;
  const columns = Math.min(40, Math.max(8, Math.ceil(Math.sqrt(Math.max(1, count) * 2))));
  const rowSpacing = Math.min(2.3, 47 / Math.max(1, Math.ceil(count / columns)));
  const update = (now: number) => {
    const shift = flowing ? frac(now / cycleSeconds) * count : 0;
    for (let i = 0; i < count; i++) {
      const slot = ((i - shift) % count + count) % count; // continuous, 0 = front
      const row = Math.floor(slot / columns), along = slot - row * columns;
      const col = row % 2 === 0 ? along : columns - 1 - along; // serpentine queue
      const x = (col - (columns - 1) / 2) * Math.min(2.15, 85 / columns);
      const z = -10 + slot / columns * rowSpacing;
      dummy.position.set(x, 1, z); dummy.updateMatrix(); bodies.setMatrixAt(i, dummy.matrix);
      dummy.position.y = 2; dummy.updateMatrix(); heads.setMatrixAt(i, dummy.matrix);
    }
    bodies.instanceMatrix.needsUpdate = true; heads.instanceMatrix.needsUpdate = true;
  };
  update(seconds);
  label(root, `${state.queue_length} QUEUED / ${state.wait_minutes.toFixed(1)} MIN`, [0, 8, 37], 48, state.frozen ? "#ff8b9d" : "#e6f0f5");
  return { root, entities: items, representatives: count + zoneRepresentatives, update, locate: fixedLocator(items) };
}

export function buildBaggage(data: SceneData, options: SceneOptions, seconds: number): BuiltScene {
  const root = new T.Group(); const items = entities(data, options, seconds);
  base(root, 125, 150);
  label(root, `BAGGAGE / TERMINAL ${options.terminal}`, [0, 13, -49], 65);
  label(root, "INDUCTION", [-46, 2, -31], 19);
  label(root, "SCREENING", [-46, 2, -11], 19);
  label(root, "SORTING", [-46, 2, 12], 19);
  label(root, "MAKE-UP", [-46, 2, 41], 19);
  label(root, "ARRIVALS / RECLAIM", [0, 2, 86], 41);
  const byId = new Map(items.map(e => [e.id, e]));
  const link = (a: Entity, b: Entity) => {
    const start = new T.Vector3(...a.position), end = new T.Vector3(...b.position);
    const middle = start.clone().add(end).multiplyScalar(0.5); middle.y = 0.6;
    const mesh = box(root, [1.5, 0.4, start.distanceTo(end)], [middle.x, middle.y, middle.z], 0x304e5f);
    mesh.lookAt(new T.Vector3(end.x, middle.y, end.z));
    line(root, [[start.x, 0.85, start.z], [end.x, 0.85, end.z]], 0x497f8b);
  };
  for (const source of items) {
    const next = source.id.startsWith("induction") ? items.filter(e => e.id.startsWith("screening")).slice(0, 2)
      : source.id.startsWith("screening") ? [byId.get("sorting-matrix")]
        : source.id === "sorting-matrix" ? items.filter(e => e.id.startsWith("make-up")) : [];
    for (const destination of next) if (destination) link(source, destination);
  }
  const animated: Array<{ mesh: T.InstancedMesh; handles: T.InstancedMesh; wheels: T.InstancedMesh; count: number; position: Point; dwellSeconds: number; offline: boolean }> = [];
  let representatives = 0;
  const cap = Math.max(1, Math.floor(QUALITY[options.quality].bags / Math.max(1, items.length)));
  for (const entity of items) {
    const source = data.zones.find(z => z.zone_id === entity.id)!;
    const group = new T.Group(); group.position.set(...entity.position); tag(group, entity); root.add(group);
    const arrival = entity.id.startsWith("arrival");
    box(group, [arrival ? 12 : 8, 1.3, 3.5], [0, 0.65, 0], statusColor(entity.status));
    box(group, [arrival ? 11.7 : 7.7, 0.12, 2.5], [0, 1.35, 0], 0x192c3a);
    for (const z of [-1.7, 1.7]) box(group, [arrival ? 12 : 8, 0.3, 0.15], [0, 1.6, z], 0x8da8b6);
    for (let x = -3.5; x < 4; x += 1) cylinder(group, 0.1, 1.3, [x, 0.55, 0], palette.steel);
    if (entity.id.startsWith("screening")) {
      box(group, [3, 2.3, 0.4], [0, 2.3, -1.6], palette.steel);
      box(group, [3, 2.3, 0.4], [0, 2.3, 1.6], palette.steel);
      box(group, [3, 0.5, 3.6], [0, 3.6, 0], 0x567b8f);
    }
    label(group, `${entity.id} · ${source.items}`, [0, 5.5, 0], entity.id === "sorting-matrix" ? 22 : 18, entity.status === "offline" ? "#ff8b9d" : "#b8e2ed");
    const count = representativeCount(source.items, cap); representatives += count;
    const mesh = new T.InstancedMesh(new T.BoxGeometry(0.85, 1.05, 0.65), material(palette.amber), count);
    mesh.userData.entityId = entity.id; mesh.frustumCulled = false; root.add(mesh);
    const handles = new T.InstancedMesh(new T.TorusGeometry(0.18, 0.04, 4, 8), material(0x16232d), count);
    const wheels = new T.InstancedMesh(new T.SphereGeometry(0.12, 5, 4), material(0x16232d), count * 2);
    for (const part of [handles, wheels]) { part.userData.entityId = entity.id; part.frustumCulled = false; root.add(part); }
    for (let i = 0; i < count; i++) mesh.setColorAt(i, new T.Color([0xe6aa65, 0x5bb7c4, 0x8298c5, 0xd5798c][i % 4]));
    // Little's law dwell: items / throughput. A bag crosses its belt in that sim time.
    const dwellSeconds = source.throughput_per_hour > 0 ? source.items / source.throughput_per_hour * 3600 : 0;
    animated.push({ mesh, handles, wheels, count, position: entity.position, dwellSeconds, offline: !["active", "normal", "degraded"].includes(source.status) || source.throughput_per_hour <= 0 || dwellSeconds <= 0 });
  }
  const dummy = new T.Object3D();
  const update = (now: number) => {
    for (const batch of animated) {
      const flow = batch.offline ? 0 : now / batch.dwellSeconds;
      for (let i = 0; i < batch.count; i++) {
        const phase = frac(i / Math.max(1, batch.count) + flow);
        dummy.position.set(batch.position[0] - 3 + phase * 6, 2, batch.position[2] + (i % 3 - 1) * 0.8);
        dummy.rotation.y = i % 2 * 0.2; dummy.updateMatrix(); batch.mesh.setMatrixAt(i, dummy.matrix);
        dummy.position.y += 0.65; dummy.updateMatrix(); batch.handles.setMatrixAt(i, dummy.matrix);
        dummy.position.y = 1.5;
        for (let side = 0; side < 2; side++) {
          dummy.position.x = batch.position[0] - 3 + phase * 6 + (side ? 0.3 : -0.3);
          dummy.updateMatrix(); batch.wheels.setMatrixAt(i * 2 + side, dummy.matrix);
        }
      }
      batch.mesh.instanceMatrix.needsUpdate = true;
      batch.handles.instanceMatrix.needsUpdate = true; batch.wheels.instanceMatrix.needsUpdate = true;
    }
  };
  update(seconds);
  if (!items.length) label(root, "NO CONVEYOR OBSERVATIONS", [0, 8, 0], 55, "#ffc888");
  return { root, entities: items, representatives, update, locate: fixedLocator(items) };
}

/**
 * ATC perspective: the same owner-timeline airfield plus the airspace the
 * flight owner implies — final-approach corridors marked in minutes to
 * touchdown (the compressed scale aircraft fly), the schematic holding fix
 * and data blocks. Nothing here is a clearance or a separation control.
 */
export function buildAtc(data: SceneData, options: SceneOptions, seconds: number): BuiltScene {
  const airfield = buildAirport(data, { ...options, view: "airport" }, seconds);
  const root = airfield.root; const layout = buildLayout(data);
  box(root, [820, 0.2, 300], [0, -1.25, 20], 0x0d1a27); // airspace floor beyond the field
  const geometries = data.runways.map(r => runwayFor(layout, r.runway_id)).filter((g): g is RunwayGeometry => !!g);
  const landing = new Set(data.flights.filter(f => f.direction === "arrival" && ["approach", "delayed", "landed"].includes(f.status) && f.runway_id).map(f => f.runway_id!));
  for (const runway of geometries) {
    const active = landing.has(runway.id) || data.runways.some(r => r.runway_id === runway.id && [r.operation, (r as typeof r & { current_use?: string }).current_use].includes("landing"));
    const color = active ? palette.cyan : 0x2f4b5e;
    const glide: Point[] = [], track: Point[] = [];
    for (let m = 0; m <= 20; m += 0.5) {
      const { point, altitude } = approachPoint(runway, m);
      glide.push(gridPoint(point.x, point.y, altitude)); track.push(gridPoint(point.x, point.y, 0.05));
    }
    line(root, glide, color); line(root, track, active ? 0x2f7d8a : 0x1f3443);
    for (const m of [2, 5, 10, 20]) {
      const { point, altitude } = approachPoint(runway, m);
      const at = gridPoint(point.x, point.y, altitude);
      cylinder(root, 0.25, altitude, [at[0], altitude / 2, at[2]], color);
      label(root, `${runway.id} · ${m} MIN`, [at[0], altitude + 2.5, at[2]], 16, active ? "#8ce9f2" : "#5d7d90");
    }
  }
  const holdingRunways = new Set(data.flights.filter(f => f.status === "delayed" && f.direction === "arrival").map(f => f.runway_id || geometries[0]?.id).filter(Boolean));
  for (const runway of geometries.filter(g => holdingRunways.has(g.id))) {
    const fix = holdingFix(runway); const ring: Point[] = [];
    for (let a = 0; a <= Math.PI * 2 + 0.01; a += Math.PI / 24) ring.push(gridPoint(fix.x + Math.cos(a) * HOLD_RADII.x, fix.y + Math.sin(a) * HOLD_RADII.y, 32));
    line(root, ring, palette.amber);
    label(root, `HOLD ${runway.id} · schematic fix`, gridPoint(fix.x, fix.y, 40), 26, "#ffc888");
  }
  // Data blocks: callsign, type and owner status follow each aircraft model.
  const flights = new Map(data.flights.map(f => [f.id, f]));
  for (const child of root.children) {
    const flight = flights.get(child.userData.entityId);
    if (!flight) continue;
    label(child, `${flight.flight_number} · ${flight.aircraft_type} · ${flight.status.toUpperCase()}${flight.runway_id ? ` · ${flight.runway_id}` : ""}`, [0, 8.5, 0], 26, flight.status === "delayed" ? "#ffc888" : "#9ff0ff");
  }
  return { ...airfield, entities: entities(data, options, seconds) };
}

export function buildScene(data: SceneData, options: SceneOptions, seconds: number) {
  return options.view === "airport" ? buildAirport(data, options, seconds) : options.view === "atc" ? buildAtc(data, options, seconds)
    : options.view === "passengers" ? buildPassengers(data, options, seconds) : buildBaggage(data, options, seconds);
}
