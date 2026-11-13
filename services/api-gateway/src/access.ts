import { randomBytes } from "crypto";
import { Request, Response, NextFunction, Express } from "express";
import { requireRole } from "./auth";

export const publicDeployment = process.env.PUBLIC_DEPLOYMENT === "true";
type Identity = { sub: string; jti?: string; role: string };
function identity(req: Request): Identity {
  return (req as Request & { user: Identity }).user;
}

// Gateway security state only. One replica; restart invalidates all leases.
export class Controller {
  private lease?: { session: string; owner: string; secret: string; expires: number };
  private busy = false;
  constructor(private now = Date.now, private ttl = 120_000) {}
  status() {
    const active = this.lease && this.lease.expires > this.now();
    return { owner: active ? this.lease?.owner : null,
      expires_at: active ? this.lease?.expires : null, busy: this.busy };
  }
  acquire(user: Identity, secret?: string) {
    if (!user.jti || this.busy) return null;
    if (this.lease && this.lease.expires > this.now()) {
      if (this.lease.session !== user.jti || secret !== this.lease.secret) return null;
    } else {
      this.lease = { session: user.jti, owner: user.sub,
        secret: randomBytes(32).toString("hex"), expires: 0 };
    }
    this.lease.expires = this.now() + this.ttl;
    return { ...this.status(), lease: this.lease.secret };
  }
  owns(user: Identity, secret?: string): boolean {
    return !!this.lease && !!secret && this.lease.expires > this.now() &&
      this.lease.session === user.jti && this.lease.secret === secret;
  }
  release(user: Identity, secret?: string): boolean {
    if (this.busy || !this.owns(user, secret)) return false;
    this.lease = undefined;
    return true;
  }
  begin(user: Identity, secret?: string): boolean {
    if (this.busy || !this.owns(user, secret)) return false;
    this.busy = true;
    return true;
  }
  finish() { this.busy = false; }
}
export const controller = new Controller();

export function setupControl(app: Express): void {
  app.get("/api/v1/control", (req, res) => res.json({ enabled: publicDeployment,
    controlling: controller.owns(identity(req), req.get("X-Control-Lease")), ...controller.status() }));
  app.post("/api/v1/control", requireRole("operator"), (req, res) => {
    const lease = controller.acquire(identity(req), req.get("X-Control-Lease"));
    res.setHeader("Cache-Control", "no-store");
    if (!lease) { res.status(409).json({ error: "Airport is controlled by another session or a command is pending" }); return; }
    res.json(lease);
  });
  app.delete("/api/v1/control", requireRole("operator"), (req, res) => {
    if (!controller.release(identity(req), req.get("X-Control-Lease"))) {
      res.status(409).json({ error: "Cannot release controller" }); return;
    }
    res.json({ released: true });
  });
}

// Deny new routes by default. Do not expose admin capabilities through aliases.
const reads = [
  /^\/api\/v1\/(airport|data-sources|health\/services)$/,
  /^\/api\/v1\/(flights|runways|gates|turnarounds|ground-vehicles)(\/[\w-]+){0,2}$/,
  /^\/api\/v1\/(passengers|baggage|incidents|costs)(\/[\w-]+){0,3}$/,
  /^\/api\/v1\/weather\/(current|metar|taf|history|impact|overrides|source)$/,
  /^\/api\/v1\/sim\/(status|settings|schedule|metrics|history)$/,
  /^\/api\/v1\/network\/(status|airports|arcs|gdps|propagations)(\/[\w-]+)?$/,
  /^\/api\/v1\/analysis\/(bottlenecks|recommendations|approvals|autonomous|autonomous\/log|anomalies)$/,
];
const writes = [
  /^POST \/api\/v1\/sim\/(pause|resume)$/,
  /^PATCH \/api\/v1\/sim\/(speed|settings)$/,
  /^POST \/api\/v1\/flights\/[\w-]+\/(hold|release)$/,
  /^POST \/api\/v1\/incidents(\/[\w-]+){0,2}$/,
  /^POST \/api\/v1\/analysis\/(recommendations\/[\w-]+\/apply|approvals\/[\w-]+\/(approve|reject))$/,
];
export function pathIsCanonical(path: string): boolean {
  return !path.includes("%") && !path.includes("\\") && !path.includes("//") &&
    !path.split("/").some(s => s === "." || s === "..");
}
export function publicRouteAllowed(method: string, path: string): boolean {
  if (!pathIsCanonical(path)) return false;
  if (/\/(compare|bts|adsb-states)(\/|$)/.test(path)) return false;
  if (method === "GET" || method === "HEAD") return reads.some(r => r.test(path));
  return writes.some(r => r.test(`${method} ${path}`));
}

export function accessPolicy(req: Request, res: Response, next: NextFunction): void {
  if (publicDeployment && !publicRouteAllowed(req.method, req.path)) {
    res.status(403).json({ error: "This endpoint is disabled on the public airport" }); return;
  }
  if (publicDeployment) {
    const url = new URL(req.originalUrl, "http://localhost");
    const bounds: Record<string, number> = { limit: 500, offset: 5000, window: 180,
      hours: 48, days: 7, window_minutes: 180, minutes: 180 };
    if (url.search.length > 1024 || Array.from(url.searchParams).some(([key, value]) =>
      Object.hasOwn(bounds, key) && (!/^\d+$/.test(value) || Number(value) > bounds[key]))) {
      res.status(400).json({ error: "Query exceeds public airport limits" }); return;
    }
  }
  if (req.method === "GET" || req.method === "HEAD") { next(); return; }
  requireRole("operator")(req, res, () => {
    if (!publicDeployment) { next(); return; }
    if (req.path === "/api/v1/sim/speed" &&
        ![1, 10].includes(req.body?.speed_multiplier)) {
      res.status(400).json({ error: "Public airport supports speeds 1x and 10x" }); return;
    }
    if (req.path === "/api/v1/sim/settings") {
      const body = req.body as Record<string, unknown> | undefined;
      if (!body || Array.isArray(body) ||
          (body.daily_flights !== undefined && (typeof body.daily_flights !== "number" || body.daily_flights < 50 || body.daily_flights > 100)) ||
          (body.pax_multiplier !== undefined && (typeof body.pax_multiplier !== "number" || body.pax_multiplier < 0.1 || body.pax_multiplier > 1)) ||
          Object.keys(body).some(k => !/^(daily_flights|load_factor_mean|pax_multiplier|weather_lock|wind_kt|gust_enabled|lanes_[abc]|mct_minutes|screening_units|sorting_capacity|dg_false_positive_rate|suppression_window_h|runway_incursion_rate|baggage_fire_rate|security_breach_rate|system_failure_rate)$/.test(k))) {
        res.status(400).json({ error: "Settings exceed the public airport resource limits" }); return;
      }
    }
    if (!controller.owns(identity(req), req.get("X-Control-Lease"))) {
      res.status(423).json({ error: "Acquire airport control before changing parameters" }); return;
    }
    if (!controller.begin(identity(req), req.get("X-Control-Lease"))) {
      res.status(409).json({ error: "Another command is still pending" }); return;
    }
    let completed = false;
    res.once("finish", () => { completed = true; readCacheEntries.clear(); controller.finish(); });
    res.once("close", () => {
      if (!completed) setTimeout(() => controller.finish(), 45_000).unref();
    });
    next();
  });
}

// Bounded cache coalesces identical reads from simultaneous visitors. Auth and
// policy run first. No mutation response, credential, or lease is cached.
export function readCache(req: Request, res: Response, next: NextFunction): void {
  if (!publicDeployment || req.method !== "GET") { next(); return; }
  if (readCacheEntries.size >= 32 && !readCacheEntries.has(req.originalUrl)) {
    res.status(503).json({ error: "Airport busy; retry shortly" }); return;
  }
  const key = req.originalUrl;
  const found = readCacheEntries.get(key);
  if (found && found.expires > Date.now()) {
    found.response.then(value => {
      if (res.destroyed) return;
      res.status(value.status).setHeader("Content-Type", value.type);
      res.end(value.body);
    });
    return;
  }
  let resolve!: (value: CachedResponse) => void;
  const response = new Promise<CachedResponse>(r => { resolve = r; });
  const entry = { expires: Date.now() + 32_000, response };
  readCacheEntries.set(key, entry);
  let chunks: Buffer[] = [];
  let size = 0;
  const originalWrite = res.write.bind(res);
  const originalEnd = res.end.bind(res);
  // Capture proxy streaming responses while preserving Node's overloads.
  res.write = ((chunk: Uint8Array | string, ...args: unknown[]) => {
    const b = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += b.length;
    if (size <= 512 * 1024) chunks.push(b);
    return Reflect.apply(originalWrite, res, [chunk, ...args]);
  }) as typeof res.write;
  res.end = ((chunk?: Uint8Array | string, ...args: unknown[]) => {
    if (chunk && typeof chunk !== "function") {
      const b = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      size += b.length;
      if (size <= 512 * 1024) chunks.push(b);
    }
    return Reflect.apply(originalEnd, res, [chunk, ...args]);
  }) as typeof res.end;
  res.once("finish", () => {
    resolve(size <= 512 * 1024
      ? { status: res.statusCode, type: String(res.getHeader("Content-Type") ?? "application/json"), body: Buffer.concat(chunks) }
      : { status: 503, type: "application/json", body: Buffer.from('{"error":"Response exceeds public limit"}') });
    chunks = [];
    entry.expires = Date.now() + 2000;
    setTimeout(() => { if (readCacheEntries.get(key) === entry) readCacheEntries.delete(key); }, 2100).unref();
  });
  res.once("close", () => {
    resolve({ status: 503, type: "application/json", body: Buffer.from('{"error":"Upstream disconnected"}') });
    if (res.statusCode >= 400 || !res.writableFinished) readCacheEntries.delete(key);
  });
  next();
}
type CachedResponse = { status: number; type: string; body: Buffer };
const readCacheEntries = new Map<string, { expires: number; response: Promise<CachedResponse> }>();
