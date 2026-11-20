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
