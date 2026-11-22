// CI check for the browser extension: the manifest is valid JSON, every script it names exists,
// and every script in the folder parses. Run: node scripts/check_extension.mjs
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const dir = join(import.meta.dirname, "..", "desktop-agent", "browser_extension");
const manifest = JSON.parse(readFileSync(join(dir, "manifest.json"), "utf8"));
const problems = [];

if (manifest.manifest_version !== 3) problems.push("manifest_version must be 3");
const named = [
  manifest.background?.service_worker,
  manifest.options_ui?.page,
  ...(manifest.content_scripts || []).flatMap((c) => c.js || []),
].filter(Boolean);
for (const file of named) {
  if (!existsSync(join(dir, file))) problems.push(`manifest names a missing file: ${file}`);
}
for (const cs of manifest.content_scripts || []) {
  for (const match of cs.matches || []) {
    const covered = (manifest.host_permissions || []).some((h) => match.startsWith(h.replace(/\*$/, "")) || h === match);
    if (!covered && !match.startsWith("http://127.0.0.1") && !match.startsWith("http://localhost")) {
      problems.push(`content script match ${match} is not covered by host_permissions`);
    }
  }
}
for (const file of readdirSync(dir).filter((f) => f.endsWith(".js"))) {
  try {
    execFileSync(process.execPath, ["--check", join(dir, file)], { stdio: "pipe" });
  } catch (e) {
    problems.push(`${file} does not parse: ${String(e.stderr || e).trim()}`);
  }
}

if (problems.length) {
  console.error(problems.map((p) => `- ${p}`).join("\n"));
  process.exit(1);
}
console.log(`browser extension OK (${named.length} files named in the manifest)`);
