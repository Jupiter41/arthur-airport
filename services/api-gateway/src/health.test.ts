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
  it("releases every response stream across repeated probes and recovery", async () => {
    inputs();
    mock.restoreAll();
    mock.method(kafka, "isKafkaConnected", () => true);
    mock.method(kafka, "isKafkaFresh", () => true);
    let released = 0;
    let healthy = false;
    mock.method(globalThis, "fetch", async () => ({
      ok: healthy, body: { cancel: async () => { released += 1; } },
    }));
    const failed = response();
    await handleReady({} as never, failed as never);
    assert.equal(failed.statusCode, 503);
    healthy = true;
    const recovered = response();
    await handleReady({} as never, recovered as never);
    assert.equal(recovered.statusCode, 200);
    assert.equal(released, 18);
  });

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

it("fails readiness for a mismatched owner build while operational checks remain healthy", async () => {
  const builds = require("./buildIdentity") as typeof import("./buildIdentity");
  const local = {schema_version:1,service:"api-gateway",revision:"release",dirty:false,
    shared_sha256:"contract",config_sha256:"config",integrity:true,errors:[]};
  mock.method(builds,"buildRequired",() => true);
  mock.method(builds,"getBuildIdentity",() => local);
  mock.method(kafka,"isKafkaConnected",() => true);
  mock.method(kafka,"isKafkaFresh",() => true);
  let mismatch = true;
  mock.method(globalThis,"fetch",async (url: string) => {
    if (url.endsWith("/ready")) return {ok:true};
    const key = Object.keys(UPSTREAM).find(key => url === `${UPSTREAM[key]}/build`)!;
    const names: Record<string,string> = {flights:"flight-service",passengers:"passenger-service",baggage:"baggage-service",
      weather:"weather-service",incidents:"incident-service",sim:"sim-orchestrator",analysis:"analysis-service",costs:"cost-service",planning:"planning-service"};
    return {ok:true,json:async () => ({...local,service:names[key],revision:mismatch && key === "baggage" ? "old" : local.revision})};
  });
  const rejected = response();
  await handleReady({} as never,rejected as never);
  assert.equal(rejected.statusCode,503);
  assert.equal(rejected.body.upstream,true);
  assert.equal(rejected.body.build_identity,false);
  mismatch = false;
  const accepted = response();
  await handleReady({} as never,accepted as never);
  assert.equal(accepted.statusCode,200);
});
