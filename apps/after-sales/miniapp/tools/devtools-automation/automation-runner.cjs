const fs = require("node:fs");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");
const { spawn } = require("node:child_process");
const automator = require("miniprogram-automator");

const configPathIndex = process.argv.indexOf("--config");
const configPath = configPathIndex >= 0 ? String(process.argv[configPathIndex + 1] || "") : "";
const config = configPath
  ? JSON.parse(fs.readFileSync(configPath, "utf8").replace(/^\uFEFF/, ""))
  : {};

function option(name) {
  if (config[name] !== undefined) return String(config[name] || "");
  const index = process.argv.indexOf(`--${name}`);
  return index >= 0 ? String(process.argv[index + 1] || "") : "";
}

function serializable(value, depth = 0) {
  if (depth > 4) return "[depth-limited]";
  if (value === null || value === undefined || ["string", "number", "boolean"].includes(typeof value)) {
    return value ?? null;
  }
  if (Array.isArray(value)) return value.slice(0, 30).map((item) => serializable(item, depth + 1));
  if (typeof value === "object") {
    const result = {};
    for (const [key, item] of Object.entries(value).slice(0, 30)) result[key] = serializable(item, depth + 1);
    return result;
  }
  return String(value);
}

async function elementText(element) {
  try { return await withTimeout(element.text(), 5_000, "读取组件文字"); } catch { return ""; }
}

async function attribute(element, name) {
  try { return await withTimeout(element.attribute(name), 5_000, "读取组件属性"); } catch { return ""; }
}

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function withTimeout(promise, milliseconds, label) {
  let timer;
  return Promise.race([
    promise,
    new Promise((_resolve, reject) => {
      timer = setTimeout(() => reject(new Error(`${label}超时`)), milliseconds);
    }),
  ]).finally(() => clearTimeout(timer));
}

function availablePort(preferredPort = 9420) {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", () => {
      const fallback = net.createServer();
      fallback.once("error", reject);
      fallback.listen(0, "127.0.0.1", () => {
        const address = fallback.address();
        const port = typeof address === "object" && address ? address.port : 0;
        fallback.close(() => resolve(port));
      });
    });
    server.listen(preferredPort, "127.0.0.1", () => server.close(() => resolve(preferredPort)));
  });
}

function quotedPowerShell(value) {
  return `'${String(value).replace(/'/g, "''")}'`;
}

async function launchAutomation(cliPath, projectPath) {
  const port = await availablePort();
  if (!port) throw new Error("无法分配小程序自动化端口");
  const launcherPath = path.join(os.tmpdir(), `mj-wechat-auto-${process.pid}.ps1`);
  const launcherScript = [
    "$ErrorActionPreference = 'Continue'",
    `& ${quotedPowerShell(cliPath)} auto --project ${quotedPowerShell(projectPath)} --auto-port ${port} --trust-project`,
    "exit $LASTEXITCODE",
    "",
  ].join("\r\n");
  fs.writeFileSync(launcherPath, `\uFEFF${launcherScript}`, "utf8");
  const cliOutput = [];
  const child = spawn("powershell.exe", [
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", launcherPath,
  ], {
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.once("exit", () => {
    try { fs.unlinkSync(launcherPath); } catch { /* best-effort temporary file cleanup */ }
  });
  child.stdout.on("data", (chunk) => cliOutput.push(String(chunk)));
  child.stderr.on("data", (chunk) => cliOutput.push(String(chunk)));

  const deadline = Date.now() + 45_000;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      const miniProgram = await withTimeout(
        automator.connect({ wsEndpoint: `ws://127.0.0.1:${port}` }),
        3_000,
        "连接自动化端口",
      );
      await wait(2_000);
      return miniProgram;
    } catch (reason) {
      lastError = reason;
      await wait(750);
    }
  }
  const details = cliOutput.join("").trim();
  throw new Error(`连接微信自动化端口失败：${lastError?.message || "超时"}${details ? `\n${details}` : ""}`);
}

function apiBaseUrl(projectPath) {
  const clientSource = fs.readFileSync(path.join(projectPath, "api", "client.js"), "utf8");
  const matched = clientSource.match(/https?:\/\/[^"']+/);
  if (!matched) throw new Error("无法从当前构建读取服务端地址");
  return matched[0].replace(/\/+$/, "");
}

async function authenticatedWorkspace(miniProgram, projectPath) {
  const session = await withTimeout(
    miniProgram.callWxMethod("getStorageSync", "mj.afterSales.mini.session"),
    5_000,
    "读取小程序登录会话",
  );
  if (!session?.token) throw new Error("小程序当前没有有效登录会话");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch(`${apiBaseUrl(projectPath)}/api/after-sales/mobile/v1/home`, {
      headers: { Authorization: `Bearer ${session.token}`, Accept: "application/json" },
      signal: controller.signal,
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload?.error || `任务接口返回 ${response.status}`);
    return { payload, token: session.token };
  } finally {
    clearTimeout(timeout);
  }
}

function productImageUrl(projectPath, task, product) {
  const productId = String(product?.productId || "").trim();
  if (!productId) throw new Error("相关产品缺少产品 ID");
  const rawPath = String(product?.productThumb || "").trim()
    || `/api/after-sales/product-catalog/${encodeURIComponent(productId)}/image?variant=thumbnail`;
  const url = new URL(rawPath, `${apiBaseUrl(projectPath)}/`);
  url.searchParams.set("variant", "thumbnail");
  url.searchParams.set("projectId", String(task.project.id));
  if (task.node.nodeKey) url.searchParams.set("nodeKey", String(task.node.nodeKey));
  return url;
}

async function inspectProductImage(projectPath, task, product, token) {
  const url = productImageUrl(projectPath, task, product);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20_000);
  try {
    const response = await fetch(url, {
      headers: { Authorization: `Bearer ${token}`, Accept: "image/*" },
      signal: controller.signal,
    });
    const body = await response.arrayBuffer();
    const contentType = String(response.headers.get("content-type") || "");
    if (!response.ok) throw new Error(`产品图片接口返回 ${response.status}`);
    if (!contentType.toLowerCase().startsWith("image/")) {
      throw new Error(`产品图片接口返回了非图片内容：${contentType || "未知类型"}`);
    }
    if (body.byteLength < 128) throw new Error(`产品图片内容异常，仅 ${body.byteLength} 字节`);
    return { status: response.status, contentType, bytes: body.byteLength };
  } finally {
    clearTimeout(timeout);
  }
}

async function inspectProducts(miniProgram, projectPath, screenshotPath) {
  const { payload: workspace, token } = await authenticatedWorkspace(miniProgram, projectPath);
  const relatedProductsForTask = (item) => (
    item?.project?.serviceType === "aftersales"
      ? item?.project?.businessData?.relatedProducts
      : item?.node?.businessData?.relatedProducts
  );
  const tasks = Array.isArray(workspace.tasks) ? workspace.tasks : [];
  const task = tasks.find((item) => (
    item?.project?.serviceType !== "presales"
    && Number(item?.assignment?.id) > 0
    && Array.isArray(relatedProductsForTask(item))
    && relatedProductsForTask(item).length > 0
  ));
  if (!task) throw new Error("当前账号没有可检查的售中或售后任务");
  const assignmentId = Number(task.assignment.id);
  const detailUrl = `/pages/task-detail/index?id=${assignmentId}&openSection=products`;
  let page = await withTimeout(
    miniProgram.reLaunch(detailUrl),
    15_000,
    "打开任务详情",
  );
  page = await withTimeout(miniProgram.currentPage(), 5_000, "读取当前页面");
  if (page?.path !== "pages/task-detail/index") {
    throw new Error(`任务详情跳转失败，当前页面为 ${page?.path || "未知页面"}`);
  }
  const relatedProducts = relatedProductsForTask(task);
  const imageResponse = await inspectProductImage(projectPath, task, relatedProducts[0], token);
  await wait(7_000);
  await withTimeout(miniProgram.screenshot({ path: screenshotPath }), 10_000, "生成小程序截图");
  return {
    pagePath: page?.path || "",
    query: page?.query || {},
    assignmentId,
    projectName: task.project.name,
    expectedProductCount: Array.isArray(relatedProducts) ? relatedProducts.length : 0,
    expectedManualCount: Array.isArray(workspace.productManuals)
      ? workspace.productManuals.filter((manual) => (
        manual.projectId === task.project.id && manual.nodeKey === task.node.nodeKey
      )).length
      : 0,
    imageResponse,
    screenshotPath,
  };
}

async function main() {
  const cliPath = option("cli");
  const projectPath = option("project");
  const action = option("action");
  const outputPath = option("output");
  const screenshotPath = option("screenshot");
  if (!cliPath || !projectPath || !outputPath) throw new Error("自动化参数不完整");
  if (action !== "inspect-products") throw new Error(`不支持的自动化动作：${action}`);

  let miniProgram;
  const consoleMessages = [];
  const exceptions = [];
  const hardTimeout = setTimeout(() => {
    fs.writeFileSync(outputPath, JSON.stringify({ ok: false, error: "小程序自动化执行超过 75 秒" }, null, 2));
    process.exit(2);
  }, 75_000);
  try {
    miniProgram = await launchAutomation(cliPath, projectPath);
    miniProgram.on("console", (entry) => consoleMessages.push(serializable(entry)));
    miniProgram.on("exception", (entry) => exceptions.push(serializable(entry)));
    const result = await inspectProducts(miniProgram, projectPath, screenshotPath);
    fs.writeFileSync(outputPath, JSON.stringify({
      ok: true,
      result,
      consoleMessages,
      exceptions,
    }, null, 2));
  } finally {
    clearTimeout(hardTimeout);
    if (miniProgram) miniProgram.disconnect();
  }
}

main().then(() => process.exit(0)).catch((reason) => {
  const outputPath = option("output");
  const message = reason instanceof Error ? (reason.stack || reason.message) : String(reason);
  if (outputPath) fs.writeFileSync(outputPath, JSON.stringify({ ok: false, error: message }, null, 2));
  process.stderr.write(`${message}\n`);
  process.exit(1);
});
