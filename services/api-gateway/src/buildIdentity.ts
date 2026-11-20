import { resolve } from "node:path";
import { Request, Response } from "express";

export interface BuildIdentity {
  schema_version: number;
  service: string;
  revision: string;
  dirty: boolean;
  source_sha256?: string;
  artifact_sha256?: string;
  shared_sha256?: string;
  config_sha256?: string;
  integrity: boolean;
  errors: string[];
}
export function buildRequired(): boolean { return process.env.ART_REQUIRE_BUILD_IDENTITY === "1"; }
export function getBuildIdentity(): BuildIdentity {
  try {
    const root = process.env.ART_BUILD_ROOT || process.cwd();
    const helper = require(resolve(root, "_common/build_identity.mjs")) as { inspectIdentity: (root: string) => BuildIdentity };
    return helper.inspectIdentity(root);
  } catch {
    return {schema_version:1,service:"api-gateway",revision:"unverified",dirty:true,integrity:false,errors:["build identity unavailable"]};
  }
}
export function matchesBuild(owner: BuildIdentity, local: BuildIdentity, service: string): boolean {
  return owner.schema_version === 1 && owner.integrity === true && owner.service === service &&
    owner.revision === local.revision && owner.shared_sha256 === local.shared_sha256 &&
    owner.config_sha256 === local.config_sha256;
}
export function handleBuild(_req: Request, res: Response): void { res.json(getBuildIdentity()); }
