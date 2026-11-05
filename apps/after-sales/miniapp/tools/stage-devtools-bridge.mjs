import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const projectDirectory = join(scriptDirectory, "..");
const buildDirectory = join(projectDirectory, "dist", "build", "mp-weixin");
const bridgeDirectory = join(buildDirectory, ".mj-devtools");
const sourceScript = join(scriptDirectory, "windows", "Start-MjWechatBridge.ps1");
const destinationScript = join(bridgeDirectory, "Start-MjWechatBridge.ps1");
const temporaryScript = `${destinationScript}.tmp`;
const automationEntry = join(scriptDirectory, "devtools-automation", "automation-runner.cjs");
const automationBundle = join(bridgeDirectory, "automation-runner.cjs");
const temporaryAutomationBundle = `${automationBundle}.tmp`;

await mkdir(bridgeDirectory, { recursive: true });
await Promise.all(["inbox", "outbox", "processed"].map((name) => (
  mkdir(join(bridgeDirectory, name), { recursive: true })
)));
const bridgeScript = await readFile(sourceScript, "utf8");
await writeFile(temporaryScript, `\uFEFF${bridgeScript.replace(/^\uFEFF/, "")}`, "utf8");
await rename(temporaryScript, destinationScript);
await build({
  entryPoints: [automationEntry],
  outfile: temporaryAutomationBundle,
  bundle: true,
  platform: "node",
  format: "cjs",
  target: "node18",
  logLevel: "warning",
});
await rename(temporaryAutomationBundle, automationBundle);

const configPath = join(buildDirectory, "project.config.json");
const config = JSON.parse(await readFile(configPath, "utf8"));
config.packOptions ||= {};
config.packOptions.ignore = Array.isArray(config.packOptions.ignore) ? config.packOptions.ignore : [];
if (!config.packOptions.ignore.some((entry) => entry?.type === "folder" && entry?.value === ".mj-devtools")) {
  config.packOptions.ignore.push({ type: "folder", value: ".mj-devtools" });
}
const temporaryConfigPath = `${configPath}.tmp`;
await writeFile(temporaryConfigPath, `${JSON.stringify(config, null, 2)}\n`, "utf8");
await rename(temporaryConfigPath, configPath);

// Keep simulator checks aligned with real-device preview. DevTools otherwise
// persists its local "do not verify domains" choice in this overriding file.
const privateConfigPath = join(buildDirectory, "project.private.config.json");
let privateConfig = {};
try {
  privateConfig = JSON.parse(await readFile(privateConfigPath, "utf8"));
} catch (reason) {
  if (reason?.code !== "ENOENT") throw reason;
}
privateConfig.setting ||= {};
privateConfig.setting.urlCheck = true;
const temporaryPrivateConfigPath = `${privateConfigPath}.tmp`;
await writeFile(temporaryPrivateConfigPath, `${JSON.stringify(privateConfig, null, 2)}\n`, "utf8");
await rename(temporaryPrivateConfigPath, privateConfigPath);

console.log(`WeChat DevTools bridge staged at ${destinationScript}`);
