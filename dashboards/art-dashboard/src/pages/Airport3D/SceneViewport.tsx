import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import * as T from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { disposeTree } from "./primitives";
import { buildScene, type BuiltScene } from "./scenes";
import { QUALITY, parseSimSeconds, type SceneData, type SceneOptions } from "./model";
import { VisualClock } from "./simClock";
import { useSimStore } from "../../stores/simStore";

export type CameraPreset = "overview" | "top" | "tower" | "close";
interface Runtime {
  renderer: T.WebGLRenderer; scene: T.Scene; camera: T.PerspectiveCamera;
  controls: OrbitControls; built: BuiltScene | null; marker: T.Mesh;
}
export function SceneViewport({ data, options, selectedId, onSelect, preset, cameraRevision }: {
  data: SceneData; options: SceneOptions; selectedId: string | null;
  onSelect: (id: string) => void; preset: CameraPreset; cameraRevision: number;
}) {
  const host = useRef<HTMLDivElement>(null); const runtime = useRef<Runtime | null>(null);
  const pick = useRef(onSelect); pick.current = onSelect;
  const [error, setError] = useState<string | null>(null); const [fps, setFps] = useState(0);
  const [representatives, setRepresentatives] = useState(0);
  const clock = useRef(new VisualClock());
  const selected = useRef(selectedId); selected.current = selectedId;
  const sim = useSimStore(s => s.status);
  const [shownTime, setShownTime] = useState<number | null>(null);
  // Every observed tick, speed change or pause re-anchors the visual clock.
  useEffect(() => {
    clock.current.observe(parseSimSeconds(sim.sim_time), performance.now(), sim.speed_multiplier, sim.paused);
  }, [sim.sim_time, sim.speed_multiplier, sim.paused]);

  useEffect(() => {
    const container = host.current; if (!container) return;
    let renderer: T.WebGLRenderer;
    try { renderer = new T.WebGLRenderer({ antialias: true, powerPreference: "low-power" }); }
    catch { setError("3D rendering is unavailable on this device. Use the operational views below."); return; }
    renderer.outputColorSpace = T.SRGBColorSpace;
    renderer.setClearColor(0x0c1725); renderer.domElement.setAttribute("aria-label", "Interactive 3D airport. Use the entity list to inspect with a keyboard.");
    renderer.domElement.setAttribute("role", "img");
    renderer.domElement.style.width = "100%"; renderer.domElement.style.height = "100%"; renderer.domElement.style.display = "block";
    container.appendChild(renderer.domElement);
    const scene = new T.Scene(); scene.fog = new T.Fog(0x0c1725, 330, 720);
    const camera = new T.PerspectiveCamera(42, 1, 0.1, 1600); camera.position.set(170, 175, 220);
    const controls = new OrbitControls(camera, renderer.domElement); controls.target.set(0, 0, 0);
    controls.maxPolarAngle = Math.PI / 2.1; controls.minDistance = 12; controls.maxDistance = 600;
    controls.enableDamping = false; controls.update();
    scene.add(new T.HemisphereLight(0xc6e5ff, 0x344647, 2.4));
    const sun = new T.DirectionalLight(0xffffff, 2.7); sun.position.set(-100, 200, 70); scene.add(sun);
    const marker = new T.Mesh(new T.RingGeometry(3, 3.3, 40), new T.MeshBasicMaterial({ color: 0x7ce7ee, side: T.DoubleSide, depthTest: false }));
    marker.rotation.x = -Math.PI / 2; marker.visible = false; marker.renderOrder = 10; scene.add(marker);
    const state: Runtime = { renderer, scene, camera, controls, built: null, marker }; runtime.current = state;
    const resize = () => {
      const width = Math.max(1, container.clientWidth), height = Math.max(1, container.clientHeight);
      camera.aspect = width / height; camera.fov = camera.aspect < 1 ? 65 : 42;
      camera.updateProjectionMatrix(); renderer.setSize(width, height, false);
    };
    const observer = new ResizeObserver(resize); observer.observe(container); resize();
    const lost = (event: Event) => { event.preventDefault(); setError("The graphics context was lost. Reload this page or continue in the 2D views."); };
    renderer.domElement.addEventListener("webglcontextlost", lost);
    const ray = new T.Raycaster(); const pointer = new T.Vector2(); let down = { x: 0, y: 0 };
    const pointerDown = (event: PointerEvent) => { down = { x: event.clientX, y: event.clientY }; };
    const pointerUp = (event: PointerEvent) => {
      if (Math.hypot(event.clientX - down.x, event.clientY - down.y) > 5 || !state.built) return;
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
      ray.setFromCamera(pointer, camera);
      for (const hit of ray.intersectObject(state.built.root, true)) {
        let object: T.Object3D | null = hit.object;
        while (object) {
          if (typeof object.userData.entityId === "string") { pick.current(object.userData.entityId); return; }
          object = object.parent;
        }
      }
    };
    renderer.domElement.addEventListener("pointerdown", pointerDown); renderer.domElement.addEventListener("pointerup", pointerUp);
    let frame = 0, previous = 0, statsAt = performance.now(), frames = 0;
    const reduced = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const animate = (at: number) => {
      frame = requestAnimationFrame(animate);
      if (at - previous < 1000 / 30 - 1 || document.hidden) return;
      previous = at;
      // Motion is a pure function of owner facts and simulation time. The
      // clock extrapolates between ticks only at source speed, stops when the
      // source is paused, and never runs more than two wall-seconds ahead.
      // Reduced motion steps once per observed tick.
      const now = clock.current.now(at, reduced);
      if (now !== null && state.built) {
        state.built.update(now);
        const target = selected.current ? state.built.locate(selected.current) : null;
        state.marker.visible = !!target;
        if (target) state.marker.position.set(target.x, Math.max(0.3, target.y - 0.6), target.z);
      }
      renderer.render(scene, camera); frames++;
      if (at - statsAt > 1500) { setFps(Math.round(frames * 1000 / (at - statsAt))); setShownTime(now); frames = 0; statsAt = at; }
    };
    frame = requestAnimationFrame(animate);
    return () => {
      cancelAnimationFrame(frame); observer.disconnect(); controls.dispose();
      renderer.domElement.removeEventListener("webglcontextlost", lost);
      renderer.domElement.removeEventListener("pointerdown", pointerDown); renderer.domElement.removeEventListener("pointerup", pointerUp);
      disposeTree(scene); renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove(); runtime.current = null;
    };
  }, []);

  useEffect(() => {
    const state = runtime.current; if (!state) return;
    if (state.built) { state.scene.remove(state.built.root); disposeTree(state.built.root); }
    const now = clock.current.now(performance.now()) ?? parseSimSeconds(useSimStore.getState().status.sim_time) ?? 0;
    state.built = buildScene(data, options, now); state.scene.add(state.built.root);
    state.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, QUALITY[options.quality].ratio));
    setRepresentatives(state.built.representatives);
    const target = selectedId ? state.built.locate(selectedId) : null;
    state.marker.visible = !!target;
    if (target) state.marker.position.set(target.x, Math.max(0.3, target.y - 0.6), target.z);
  }, [data, options, selectedId]);

  useEffect(() => {
    const state = runtime.current; if (!state) return;
    const airport = options.view === "airport", atc = options.view === "atc";
    const located = preset === "close" && selectedId ? state.built?.locate(selectedId) ?? null : null;
    // ATC frames the field plus both compressed approach corridors.
    state.scene.fog = new T.Fog(0x0c1725, atc ? 700 : 330, atc ? 1500 : 720);
    state.controls.maxDistance = atc ? 1100 : 600; state.camera.far = atc ? 2600 : 1600; state.camera.updateProjectionMatrix();
    if (preset === "tower" && (airport || atc)) {
      // Tower cab (static architecture at the west apron) looking along the runways.
      state.camera.position.set(-106, 23, 47); state.controls.target.set(atc ? 60 : 20, 0, 62); state.controls.update();
      return;
    }
    const target = located ?? new T.Vector3(0, 0, airport ? 0 : atc ? 40 : 10);
    const offset = preset === "top" ? new T.Vector3(0, atc ? 760 : airport ? 310 : 160, 0.1)
      : preset === "close" ? new T.Vector3(25, 22, 30) : atc ? new T.Vector3(0, 420, 470) : options.view === "passengers" ? new T.Vector3(135, 125, 160) : new T.Vector3(airport ? 165 : 92, airport ? 175 : 88, airport ? 220 : 115);
    state.camera.position.copy(target).add(offset); state.controls.target.copy(target); state.controls.update();
    // Selection alone highlights. Camera moves only on an explicit preset/focus action.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset, cameraRevision, options.view]);

  if (error) return <div role="alert" className="min-h-[420px] rounded-2xl border border-amber-400/30 bg-panel p-8 flex flex-col justify-center gap-5"><h2 className="text-xl">3D view unavailable</h2><p className="text-gray-400">{error}</p><div className="flex flex-wrap gap-4 text-sky-300"><Link to="/ground-ops?3d=off">Ground operations →</Link><Link to="/passengers?3d=off">Passenger flow →</Link><Link to="/baggage?3d=off">Baggage tracker →</Link></div></div>;
  return <div className="relative rounded-2xl overflow-hidden border border-sky-300/15 bg-[#0c1725]">
    <div ref={host} className="h-[460px] sm:h-[600px] xl:h-[690px] w-full touch-none" data-testid="scene-host" />
    <div className="spatial-overlay absolute top-4 left-4 pointer-events-none rounded-lg bg-[#0b1826] border border-slate-600/40 px-3 py-2 text-[10px] font-mono text-slate-300 space-y-1"><p className="text-cyan-200">KART / SPATIAL TWIN</p><p>{options.view.toUpperCase()} · {options.quality.toUpperCase()}</p><p>{representatives} {options.view === "airport" || options.view === "atc" ? "aircraft models" : "representative figures"} · {fps || "—"} FPS</p><p data-testid="scene-sim-time">{shownTime === null ? "SIM —" : `SIM ${new Date(shownTime * 1000).toISOString().slice(11, 19)}Z${sim.paused ? " · PAUSED" : ` · ×${sim.speed_multiplier}`}`}</p></div>
    <p className="spatial-overlay bg-[#0b1826] rounded px-3 py-2 absolute bottom-3 left-3 right-3 text-[10px] text-slate-300 pointer-events-none">Drag to orbit · right-drag / two fingers to pan · scroll / pinch to zoom · select a model or use the entity list</p>
  </div>;
}
