import { timingSafeEqual } from "crypto";
import jwt from "jsonwebtoken";
import { Request, Response, NextFunction } from "express";

// The one insecure default we refuse to run with in production.
const DEV_JWT_SECRET = "art-digital-twin-dev";

const JWT_SECRET = process.env.JWT_SECRET ?? DEV_JWT_SECRET;
const JWT_EXPIRES_IN = parseInt(process.env.JWT_EXPIRES_IN ?? "86400", 10);

const IS_PROD = process.env.NODE_ENV === "production";

// ── Roles (hierarchical) ─────────────────────────────────────
// viewer < operator < approver. A route that requires role R is satisfied by
// any role of rank >= rank(R). approver is the human-in-the-loop tier that can
// sign off on safety-guarded proposals (A9); operator performs routine actions.
export type Role = "viewer" | "operator" | "approver";
export const ROLE_RANK: Record<Role, number> = {
  viewer: 0,
  operator: 1,
  approver: 2,
};

type Client = { secret: string; role: Role };

/**
 * Client registry. Configured via the AUTH_CLIENTS env var (JSON:
 * `{"dashboard":{"secret":"...","role":"operator"}}`). In production this MUST
 * be provided — there is no built-in credential. In non-production we fall back
 * to a single well-known dev client so `docker compose up` works out of the box.
 */
function loadClients(): Record<string, Client> {
  const raw = process.env.AUTH_CLIENTS;
  if (raw) {
    try {
      const parsed = JSON.parse(raw) as Record<string, Client>;
      // Basic shape validation — drop malformed entries rather than trust them.
      const clean: Record<string, Client> = {};
      for (const [id, c] of Object.entries(parsed)) {
        if (
          c &&
          typeof c.secret === "string" &&
          c.secret.length > 0 &&
          (c.role === "viewer" || c.role === "operator" || c.role === "approver")
        ) {
          clean[id] = { secret: c.secret, role: c.role };
        } else {
          console.warn(`auth: ignoring malformed AUTH_CLIENTS entry "${id}"`);
        }
      }
      return clean;
    } catch {
      console.error("auth: AUTH_CLIENTS is not valid JSON — no clients loaded");
      return {};
    }
  }

  if (IS_PROD) {
    // Fail closed: no default credential in production.
    return {};
  }

  // Dev convenience only. The dashboard is the single operator console and
  // doubles as the approver in this single-client demo topology.
  return {
    dashboard: { secret: "art-dev-secret", role: "approver" },
  };
}

const CLIENTS = loadClients();

/**
 * True when the gateway is safe to issue/verify tokens. In production we refuse
 * to run with the known dev secret or with no configured clients — either would
 * mean anyone can mint an operator token.
 */
export function isSecureConfig(): boolean {
  if (!IS_PROD) return true;
  if (JWT_SECRET === DEV_JWT_SECRET) return false;
  if (Object.keys(CLIENTS).length === 0) return false;
  return true;
}

if (IS_PROD && !isSecureConfig()) {
  // Loud, but do not crash the process here — handleToken/authMiddleware fail
  // closed below, so the gateway stays up (serving 503s on auth) rather than
  // taking the whole deployment down on a config mistake.
  console.error(
    "auth: INSECURE CONFIG in production — set a non-default JWT_SECRET and " +
      "provide AUTH_CLIENTS. Token issuance and verification are disabled.",
  );
}

function secretsMatch(provided: string, expected: string): boolean {
  const a = Buffer.from(provided);
  const b = Buffer.from(expected);
  // timingSafeEqual throws on length mismatch — guard first, still constant-time
  // for equal-length inputs (the security-relevant case).
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

export function handleToken(req: Request, res: Response): void {
  if (!isSecureConfig()) {
    res.status(503).json({ error: "auth not configured" });
    return;
  }

  const { client_id, secret } = req.body ?? {};

  if (!client_id) {
    res.status(400).json({ error: "client_id required" });
    return;
  }

  const client = CLIENTS[client_id as string];
  // Reject unknown clients and bad secrets identically (no client enumeration).
  // Note: no dev backdoor — credentials are always validated.
  if (
    !client ||
    typeof secret !== "string" ||
    !secretsMatch(secret, client.secret)
  ) {
    res.status(401).json({ error: "invalid credentials" });
    return;
  }

  const token = jwt.sign({ sub: client_id, role: client.role }, JWT_SECRET, {
    expiresIn: JWT_EXPIRES_IN,
  });

  res.json({ token, expires_in: JWT_EXPIRES_IN, role: client.role });
}

export function authMiddleware(
  req: Request,
  res: Response,
  next: NextFunction,
): void {
  if (!isSecureConfig()) {
    res.status(503).json({ error: "auth not configured" });
    return;
  }

  const header = req.headers.authorization ?? "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : "";

  if (!token) {
    res.status(401).json({ error: "missing token" });
    return;
  }

  try {
    const decoded = jwt.verify(token, JWT_SECRET);
    (req as unknown as Record<string, unknown>).user = decoded;
    next();
  } catch {
    res.status(401).json({ error: "invalid or expired token" });
  }
}

/**
 * Role-gate middleware. Requires the authenticated user to hold at least the
 * given role (per ROLE_RANK). Mount AFTER authMiddleware, on the routes whose
 * execution must be gated by identity — e.g. approving a safety-guarded
 * proposal requires `approver`.
 */
export function requireRole(
  minRole: Role,
): (req: Request, res: Response, next: NextFunction) => void {
  const required = ROLE_RANK[minRole];
  return (req, res, next) => {
    const user = (req as unknown as Record<string, unknown>).user as
      | { role?: string }
      | undefined;
    const role = user?.role as Role | undefined;
    const rank = role ? ROLE_RANK[role] : undefined;
    if (rank === undefined || rank < required) {
      res.status(403).json({ error: "insufficient role", required: minRole });
      return;
    }
    next();
  };
}

/**
 * Extract and verify a JWT from a URL query string or Authorization header.
 * Used for WebSocket upgrade requests.
 */
type TokenRequest = {
  headers: Request["headers"];
  url?: string;
};

export function verifyTokenFromRequest(req: TokenRequest): boolean {
  if (!isSecureConfig()) return false;

  const header = req.headers.authorization ?? "";
  let token = header.startsWith("Bearer ") ? header.slice(7) : "";

  if (!token && req.url) {
    try {
      const url = new URL(req.url, "http://localhost");
      token = url.searchParams.get("token") ?? "";
    } catch {
      token = "";
    }
  }
  if (!token) return false;

  try {
    jwt.verify(token, JWT_SECRET);
    return true;
  } catch {
    return false;
  }
}
