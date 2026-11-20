/** RC14: hashing matches build_identity.py (path NUL file SHA newline). */
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, relative, extname, basename } from "node:path";
import { fileURLToPath } from "node:url";

function files(root) {
  return readdirSync(root, { withFileTypes: true }).flatMap(entry => {
    if (["__pycache__", ".git", "node_modules"].includes(entry.name)) return [];
    const path = join(root, entry.name);
    return entry.isDirectory() ? files(path) : entry.isFile() ? [path] : [];
  });
}
export function treeHash(root, kind) {
  const digest = createHash("sha256");
  for (const path of files(root).sort()) {
    const name = relative(root, path).replaceAll("\\", "/");
    const include = kind === "shared" ? [".py", ".mjs"].includes(extname(path)) :
      kind === "config" ? [".yaml", ".yml", ".json"].includes(extname(path)) :
      kind === "source" ? [".ts", ".tsx", ".json", ".html", ".css"].includes(extname(path)) :
      kind === "gateway" ? [".js", ".json"].includes(extname(path)) : basename(path) !== "build.json";
    if (include) digest.update(name + "\0" + createHash("sha256").update(readFileSync(path)).digest("hex") + "\n");
  }
  return digest.digest("hex");
}
export function sourceHash(root) {
  const digest = createHash("sha256").update(treeHash(join(root,"src"),"source"));
  for (const name of ["package.json","package-lock.json","index.html"]) {
    try { digest.update(name + "\0" + createHash("sha256").update(readFileSync(join(root,name))).digest("hex") + "\n"); }
    catch (error) { if (error.code !== "ENOENT") throw error; }
  }
  return digest.digest("hex");
}
export function inspectIdentity(root = process.env.ART_BUILD_ROOT || "/app") {
  try {
    const value = JSON.parse(readFileSync(join(root, "build-identity.json"), "utf8"));
    const errors = [];
    if (value.schema_version !== 1 || !value.revision || value.revision === "unversioned") errors.push("unversioned build");
    for (const [key, kind, path] of [
      ["artifact_sha256", "gateway", join(root,"dist")],
      ["shared_sha256", "shared", join(root,"_common")],
      ["config_sha256", "config", join(root,"config")],
    ]) if (value[key] !== treeHash(path,kind)) errors.push(`${key} mismatch`);
    return {...value, integrity: errors.length === 0, errors};
  } catch {
    return {schema_version:1,service:"unknown",revision:"unverified",dirty:true,integrity:false,errors:["build identity unavailable"]};
  }
}
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  if (process.argv[2] === "--source") { process.stdout.write(sourceHash(process.argv[3])); process.exit(0); }
  const [service, revision = "unversioned", dirty = "true"] = process.argv.slice(2);
  const root = process.cwd();
  const value = {schema_version:1,service,revision,dirty:dirty === "true",
    source_sha256:sourceHash(root),
    artifact_sha256:treeHash(join(root,"dist"),service === "dashboard" ? "dashboard" : "gateway"),
    shared_sha256:treeHash(join(root,"_common"),"shared"),
    config_sha256:treeHash(join(root,"config"),"config")};
  if (service === "dashboard") value.artifact_files = Object.fromEntries(files(join(root,"dist")).sort()
    .filter(path => basename(path) !== "build.json")
    .map(path => [relative(join(root,"dist"),path),createHash("sha256").update(readFileSync(path)).digest("hex")]));
  writeFileSync(service === "dashboard" ? "dist/build.json" : "build-identity.json", JSON.stringify(value)+"\n");
}
