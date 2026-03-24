import jwt from "jsonwebtoken";
import { Request, Response, NextFunction } from "express";

const JWT_SECRET = process.env.JWT_SECRET ?? "art-digital-twin-dev";
const JWT_EXPIRES_IN = parseInt(process.env.JWT_EXPIRES_IN ?? "86400", 10);

export function handleToken(req: Request, res: Response): void {
  const { client_id, secret } = req.body ?? {};

  if (!client_id) {
    res.status(400).json({ error: "client_id required" });
    return;
  }

  // In development mode, accept any credentials
  const isDev = process.env.NODE_ENV !== "production";
  if (!isDev && secret !== process.env.AUTH_SECRET) {
    res.status(401).json({ error: "invalid credentials" });
    return;
  }

  const token = jwt.sign({ sub: client_id, role: "operator" }, JWT_SECRET, {
    expiresIn: JWT_EXPIRES_IN,
  });

  res.json({ token, expires_in: JWT_EXPIRES_IN });
}

export function authMiddleware(
  req: Request,
  res: Response,
  next: NextFunction,
): void {
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
 * Extract and verify a JWT from a URL query string or Authorization header.
 * Used for WebSocket upgrade requests.
 */
export function verifyTokenFromRequest(req: Request): boolean {
  const header = req.headers.authorization ?? "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : "";
  if (!token) return false;

  try {
    jwt.verify(token, JWT_SECRET);
    return true;
  } catch {
    return false;
  }
}
