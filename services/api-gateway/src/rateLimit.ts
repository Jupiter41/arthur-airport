import rateLimit from "express-rate-limit";
import { Request, Response } from "express";
import client from "prom-client";

const rateLimitHits = new client.Counter({
  name: "gateway_rate_limit_hits_total",
  help: "Rate limit rejections",
  labelNames: ["tier"],
});

function limitHandler(tier: string) {
  return (_req: Request, res: Response): void => {
    rateLimitHits.inc({ tier });
    res.status(429).json({ error: "Too many requests" });
  };
}

/**
 * Extract rate-limit key: prefer JWT subject (per-token), fall back to IP.
 * The authMiddleware sets `req.user` with the decoded JWT payload.
 */
function keyGenerator(req: Request): string {
  const user = (req as unknown as Record<string, unknown>).user as
    | { sub?: string }
    | undefined;
  if (user?.sub) {
    return `token:${user.sub}`;
  }
  return `ip:${req.ip ?? "unknown"}`;
}

/**
 * Default rate limiter: 200 requests per 60 seconds
 */
export const defaultLimiter = rateLimit({
  windowMs: 60_000,
  limit: 200,
  standardHeaders: true,
  legacyHeaders: false,
  keyGenerator,
  handler: limitHandler("default"),
});

/**
 * Heavy endpoint rate limiter: 10 requests per 60 seconds
 * Applied to /api/v1/airport
 */
export const heavyLimiter = rateLimit({
  windowMs: 60_000,
  limit: 10,
  standardHeaders: true,
  legacyHeaders: false,
  keyGenerator,
  handler: limitHandler("heavy"),
});

/**
 * Sim reset rate limiter: 1 request per 300 seconds
 */
export const simResetLimiter = rateLimit({
  windowMs: 300_000,
  limit: 1,
  standardHeaders: true,
  legacyHeaders: false,
  keyGenerator,
  handler: limitHandler("sim_reset"),
});

/**
 * Incident inject rate limiter: 5 requests per 60 seconds
 */
export const injectLimiter = rateLimit({
  windowMs: 60_000,
  limit: 5,
  standardHeaders: true,
  legacyHeaders: false,
  keyGenerator,
  handler: limitHandler("inject"),
});
