import { describe, it } from "node:test";
import assert from "node:assert/strict";
import jwt from "jsonwebtoken";

import {
  handleToken,
  authMiddleware,
  requireRole,
  verifyTokenFromRequest,
} from "./auth";

// auth.ts reads JWT_SECRET at module-load time; with no env set it falls back
// to the dev default. Sign test tokens with the same value so verify() agrees.
const SECRET = process.env.JWT_SECRET ?? "art-digital-twin-dev";
// The built-in dev client (NODE_ENV != production): dashboard / art-dev-secret,
// role "approver". Tests run with NODE_ENV unset, so this registry is active.
const DEV_CLIENT_SECRET = "art-dev-secret";

function mockRes() {
  const res = {
    statusCode: 200,
    body: undefined as unknown,
    status(code: number) {
      this.statusCode = code;
      return this;
    },
    json(body: unknown) {
      this.body = body;
      return this;
    },
  };
  return res;
}

describe("handleToken", () => {
  it("rejects a request with no client_id (400)", () => {
    const res = mockRes();
    handleToken({ body: {} } as never, res as never);
    assert.equal(res.statusCode, 400);
  });

  it("rejects a known client with no secret (401) — no dev backdoor", () => {
    const res = mockRes();
    handleToken({ body: { client_id: "dashboard" } } as never, res as never);
    assert.equal(res.statusCode, 401);
  });

  it("rejects a known client with the wrong secret (401)", () => {
    const res = mockRes();
    handleToken(
      { body: { client_id: "dashboard", secret: "wrong" } } as never,
      res as never,
    );
    assert.equal(res.statusCode, 401);
  });

  it("rejects an unknown client id (401)", () => {
    const res = mockRes();
    handleToken(
      { body: { client_id: "nobody", secret: DEV_CLIENT_SECRET } } as never,
      res as never,
    );
    assert.equal(res.statusCode, 401);
  });

  it("issues a verifiable JWT carrying the client's role for valid credentials", () => {
    const res = mockRes();
    handleToken(
      { body: { client_id: "dashboard", secret: DEV_CLIENT_SECRET } } as never,
      res as never,
    );
    const body = res.body as { token?: string; role?: string };
    assert.ok(body.token, "expected a token in the response");
    assert.equal(body.role, "approver");
    const decoded = jwt.verify(body.token as string, SECRET) as {
      sub: string;
      role: string;
    };
    assert.equal(decoded.sub, "dashboard");
    assert.equal(decoded.role, "approver");
  });
});

describe("authMiddleware", () => {
  it("rejects a missing Authorization header (401) and does not call next()", () => {
    const res = mockRes();
    let nextCalled = false;
    authMiddleware({ headers: {} } as never, res as never, (() => {
      nextCalled = true;
    }) as never);
    assert.equal(res.statusCode, 401);
    assert.equal(nextCalled, false);
  });

  it("rejects a token signed with the wrong secret (401)", () => {
    const res = mockRes();
    let nextCalled = false;
    const bad = jwt.sign({ sub: "x" }, "not-the-secret");
    authMiddleware(
      { headers: { authorization: `Bearer ${bad}` } } as never,
      res as never,
      (() => {
        nextCalled = true;
      }) as never,
    );
    assert.equal(res.statusCode, 401);
    assert.equal(nextCalled, false);
  });

  it("accepts a valid token and calls next()", () => {
    const res = mockRes();
    let nextCalled = false;
    const good = jwt.sign({ sub: "dashboard", role: "operator" }, SECRET);
    authMiddleware(
      { headers: { authorization: `Bearer ${good}` } } as never,
      res as never,
      (() => {
        nextCalled = true;
      }) as never,
    );
    assert.equal(nextCalled, true);
    assert.equal(res.statusCode, 200);
  });
});

describe("requireRole (RBAC)", () => {
  function runGate(minRole: "viewer" | "operator" | "approver", role?: string) {
    const res = mockRes();
    let nextCalled = false;
    const req = { user: role ? { role } : undefined } as never;
    requireRole(minRole)(req, res as never, (() => {
      nextCalled = true;
    }) as never);
    return { res, nextCalled };
  }

  it("allows a role of equal rank", () => {
    const { nextCalled } = runGate("approver", "approver");
    assert.equal(nextCalled, true);
  });

  it("allows a role of higher rank", () => {
    const { nextCalled } = runGate("operator", "approver");
    assert.equal(nextCalled, true);
  });

  it("rejects a role of lower rank (403)", () => {
    const { res, nextCalled } = runGate("approver", "operator");
    assert.equal(nextCalled, false);
    assert.equal(res.statusCode, 403);
  });

  it("rejects a request with no role (403)", () => {
    const { res, nextCalled } = runGate("operator");
    assert.equal(nextCalled, false);
    assert.equal(res.statusCode, 403);
  });

  it("rejects an unknown role value (403)", () => {
    const { res, nextCalled } = runGate("viewer", "superadmin");
    assert.equal(nextCalled, false);
    assert.equal(res.statusCode, 403);
  });
});

describe("verifyTokenFromRequest", () => {
  it("returns false when no token is present", () => {
    assert.equal(verifyTokenFromRequest({ headers: {} }), false);
  });

  it("accepts a valid token from the Authorization header", () => {
    const good = jwt.sign({ sub: "dashboard" }, SECRET);
    assert.equal(
      verifyTokenFromRequest({ headers: { authorization: `Bearer ${good}` } }),
      true,
    );
  });

  it("accepts a valid token from the ?token= query string (WebSocket upgrade)", () => {
    const good = jwt.sign({ sub: "dashboard" }, SECRET);
    assert.equal(
      verifyTokenFromRequest({ headers: {}, url: `/ws?token=${good}` }),
      true,
    );
  });

  it("rejects a malformed token in the query string", () => {
    assert.equal(
      verifyTokenFromRequest({ headers: {}, url: "/ws?token=garbage" }),
      false,
    );
  });
});
