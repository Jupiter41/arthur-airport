import { afterEach, describe, it, mock } from "node:test";
import assert from "node:assert/strict";
import { handleReady, handleServicesHealth } from "./health";
import { UPSTREAM } from "./proxy";

const kafka = require("./kafka") as {
  isKafkaConnected: () => boolean;
  isKafkaFresh: () => boolean;
  getLastMessageAt: () => number | null;
};

function response() {
  return {
    statusCode: 200,
    body: {} as Record<string, unknown>,
    status(code: number) { this.statusCode = code; return this; },
    json(body: Record<string, unknown>) { this.body = body; return this; },
  };
}

function inputs(unavailable?: string) {
  mock.method(kafka, "isKafkaConnected", () => true);
  mock.method(kafka, "isKafkaFresh", () => true);
  mock.method(kafka, "getLastMessageAt", () => null);
  const seen: string[] = [];
  mock.method(globalThis, "fetch", async (url: string) => {
    seen.push(url);
    return { ok: !unavailable || url !== `${UPSTREAM[unavailable]}/ready` };
  });
  return seen;
}

afterEach(() => mock.restoreAll());

describe("complete digital twin readiness", () => {
  it("checks readiness of all nine upstreams", async () => {
    const seen = inputs();
    const res = response();
    await handleReady({} as never, res as never);
    assert.equal(res.statusCode, 200);
    assert.equal(seen.length, 9);
    assert.ok(seen.every(url => url.endsWith("/ready")));
    assert.equal(Object.keys(res.body.services as object).length, 9);
  });

  for (const service of ["planning", "costs", "analysis"]) {
    it(`returns 503 when ${service} is unavailable`, async () => {
      inputs(service);
      const res = response();
      await handleReady({} as never, res as never);
      assert.equal(res.statusCode, 503);
      assert.equal(res.body.upstream, false);
    });
  }

  it("services health does not report an unready analysis as healthy", async () => {
    inputs("analysis");
    const res = response();
    await handleServicesHealth({} as never, res as never);
    assert.equal(res.body.analysis_service, "unavailable");
    assert.equal(res.body.planning_service, "ok");
  });
});
