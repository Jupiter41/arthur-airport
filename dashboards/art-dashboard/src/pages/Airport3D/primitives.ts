import * as T from "three";
import type { Point } from "./model";

export const palette = { cyan: 0x53cddd, blue: 0x659fe8, amber: 0xffba66, red: 0xfb6879, green: 0x63dbb4, steel: 0x354b61, white: 0xd9e9ef };
export function material(color: T.ColorRepresentation, metalness = 0.12) {
  return new T.MeshStandardMaterial({ color, roughness: 0.65, metalness });
}
export function box(parent: T.Object3D, size: Point, position: Point, color: T.ColorRepresentation) {
  const mesh = new T.Mesh(new T.BoxGeometry(...size), material(color));
  mesh.position.set(...position); parent.add(mesh); return mesh;
}
export function cylinder(parent: T.Object3D, radius: number, height: number, position: Point, color: T.ColorRepresentation) {
  const mesh = new T.Mesh(new T.CylinderGeometry(radius, radius, height, 12), material(color));
  mesh.position.set(...position); parent.add(mesh); return mesh;
}
export function label(parent: T.Object3D, text: string, position: Point, width = 14, color = "#d5ecf7") {
  const canvas = document.createElement("canvas"); canvas.width = 512; canvas.height = 96;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.fillStyle = "rgba(11,24,38,0.88)"; ctx.fillRect(0, 0, 512, 96);
  ctx.font = "500 40px system-ui"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillStyle = color;
  ctx.fillText(text, 256, 48, 490);
  const texture = new T.CanvasTexture(canvas); texture.colorSpace = T.SRGBColorSpace;
  const sprite = new T.Sprite(new T.SpriteMaterial({ map: texture, depthTest: false, sizeAttenuation: false }));
  const screenWidth = Math.min(0.22, width * 0.009);
  sprite.position.set(...position); sprite.scale.set(screenWidth, screenWidth * 96 / 512, 1); parent.add(sprite);
}
export function line(parent: T.Object3D, points: Point[], color: T.ColorRepresentation) {
  const mesh = new T.Line(new T.BufferGeometry().setFromPoints(points.map(p => new T.Vector3(...p))), new T.LineBasicMaterial({ color }));
  parent.add(mesh); return mesh;
}
function wing(parent: T.Object3D, vertices: number[], color: number) {
  const shape = new T.Shape(); shape.moveTo(vertices[0], vertices[1]);
  for (let i = 2; i < vertices.length; i += 2) shape.lineTo(vertices[i], vertices[i + 1]);
  shape.closePath();
  const mesh = new T.Mesh(new T.ExtrudeGeometry(shape, { depth: 0.15, bevelEnabled: false }), material(color));
  mesh.rotation.x = Math.PI / 2; mesh.position.y = 0.7; parent.add(mesh);
}

/** Original procedural twin-engine jet; no third-party model assets. Nose faces -Z. */
export function aircraft(wideBody = false) {
  const root = new T.Group();
  const fuselage = new T.Mesh(new T.CapsuleGeometry(0.65, 8, 6, 12), material(palette.white));
  fuselage.rotation.x = Math.PI / 2; fuselage.position.y = 1.2; root.add(fuselage);
  wing(root, [-0.4, -1, -6, 2.7, -5.8, 3.4, -0.3, 1.5], palette.white);
  wing(root, [0.4, -1, 6, 2.7, 5.8, 3.4, 0.3, 1.5], palette.white);
  wing(root, [-0.2, 3.1, -2.1, 4.5, -1.9, 4.9, 0, 4.1], palette.blue);
  wing(root, [0.2, 3.1, 2.1, 4.5, 1.9, 4.9, 0, 4.1], palette.blue);
  const tail = box(root, [0.14, 2.1, 1.6], [0, 2.25, 3.7], palette.cyan); tail.rotation.x = -0.3;
  for (const x of [-2.1, 2.1]) {
    const engine = cylinder(root, 0.42, 1.8, [x, 0.35, 0.4], palette.steel); engine.rotation.x = Math.PI / 2;
    const inlet = cylinder(root, 0.31, 0.05, [x, 0.35, -0.52], 0x111b29); inlet.rotation.x = Math.PI / 2;
    const gear = cylinder(root, 0.19, 0.55, [x / 2, 0, 1.5], 0x172231); gear.rotation.z = Math.PI / 2;
  }
  const windshield = box(root, [0.8, 0.33, 0.8], [0, 1.55, -3.7], 0x1a354d); windshield.rotation.x = -0.3;
  for (const x of [-0.65, 0.65]) for (let z = -2.6; z < 2.7; z += 0.5) box(root, [0.03, 0.18, 0.19], [x, 1.4, z], 0x244b67);
  if (wideBody) root.scale.set(1.3, 1.2, 1.4);
  return root;
}

export function vehicle(type: string, busy: boolean) {
  const root = new T.Group(); const color = busy ? palette.amber : palette.cyan;
  box(root, [1.7, 0.55, 3.4], [0, 0.4, 0], palette.steel);
  box(root, [1.6, 1.1, 1.1], [0, 1, -1.15], color);
  box(root, [1.35, 0.45, 0.05], [0, 1.2, -1.72], 0x1d3547);
  if (type === "fuel_truck") {
    const tank = cylinder(root, 0.7, 2, [0, 1.1, 0.55], palette.white); tank.rotation.x = Math.PI / 2;
  } else if (type === "stairs") {
    for (let i = 0; i < 6; i++) box(root, [1.5, 0.2 + i * 0.22, 0.38], [0, 0.8 + i * 0.11, -0.2 + i * 0.4], color);
  } else if (type === "baggage_loader") {
    const belt = box(root, [1.3, 0.2, 3.1], [0, 1.3, 0.5], palette.green); belt.rotation.x = -0.22;
  } else if (type === "catering_truck") box(root, [1.8, 1.7, 2.4], [0, 1.5, 0.55], palette.white);
  else box(root, [1.7, 0.6, 1.6], [0, 0.9, 0.4], color);
  for (const x of [-0.9, 0.9]) for (const z of [-1, 1.1]) {
    const wheel = cylinder(root, 0.35, 0.16, [x, 0.3, z], 0x111b28); wheel.rotation.z = Math.PI / 2;
  }
  return root;
}

export function disposeTree(root: T.Object3D) {
  const geometries = new Set<T.BufferGeometry>(); const materials = new Set<T.Material>(); const textures = new Set<T.Texture>();
  root.traverse(object => {
    if (object instanceof T.Mesh || object instanceof T.Line || object instanceof T.Sprite) {
      if ("geometry" in object) geometries.add(object.geometry);
      for (const mat of Array.isArray(object.material) ? object.material : [object.material]) {
        materials.add(mat);
        const map = (mat as T.MeshStandardMaterial).map;
        if (map) textures.add(map);
      }
    }
    if (object instanceof T.InstancedMesh) object.dispose();
  });
  geometries.forEach(g => g.dispose()); materials.forEach(m => m.dispose()); textures.forEach(t => t.dispose());
}
