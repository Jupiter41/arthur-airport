import { it } from "node:test";
import assert from "node:assert/strict";
import { matchesBuild, BuildIdentity } from "./buildIdentity";
const build: BuildIdentity = {schema_version:1,service:"api-gateway",revision:"abc",dirty:false,
  integrity:true,errors:[],shared_sha256:"shared",config_sha256:"config"};
it("rejects mixed revisions, contracts, configurations and unverified owner identity", () => {
  const owner = {...build,service:"flight-service"};
  assert.ok(matchesBuild(owner,build,"flight-service"));
  for (const patch of [{revision:"old"},{shared_sha256:"stale"},{config_sha256:"old"},
    {integrity:false},{service:"weather-service"},{schema_version:2}]) {
    assert.equal(matchesBuild({...owner,...patch},build,"flight-service"),false);
  }
});

it("detects changes to compiled JSON policy as well as executable JavaScript", async () => {
  const { mkdtempSync, mkdirSync, writeFileSync, rmSync } = await import("node:fs");
  const { tmpdir } = await import("node:os");
  const { join, resolve } = await import("node:path");
  const helper = require(resolve(__dirname,"../../_common/build_identity.mjs")) as {
    treeHash: (root: string,kind: string) => string;
    inspectIdentity: (root: string) => BuildIdentity;
  };
  const root = mkdtempSync(join(tmpdir(),"rc14-build-"));
  try {
    for (const dir of ["dist","_common","config"]) mkdirSync(join(root,dir));
    writeFileSync(join(root,"dist/main.js"),"module.exports = 1;");
    writeFileSync(join(root,"dist/policy.json"),'{"delivery":"snapshot"}');
    writeFileSync(join(root,"build-identity.json"),JSON.stringify({schema_version:1,service:"api-gateway",revision:"release",dirty:false,
      artifact_sha256:helper.treeHash(join(root,"dist"),"gateway"),shared_sha256:helper.treeHash(join(root,"_common"),"shared"),config_sha256:helper.treeHash(join(root,"config"),"config")}));
    assert.equal(helper.inspectIdentity(root).integrity,true);
    writeFileSync(join(root,"dist/policy.json"),'{"delivery":"stale"}');
    assert.equal(helper.inspectIdentity(root).integrity,false);
  } finally { rmSync(root,{recursive:true,force:true}); }
});
