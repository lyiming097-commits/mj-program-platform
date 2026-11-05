"use strict";

const crypto = require("node:crypto");
const http = require("node:http");
const { chromium } = require("playwright-core");

const PORT = positiveInteger(process.env.PORT, 3000);
const MAX_REQUEST_BYTES = 8 * 1024;
const MAX_PDF_BYTES = positiveInteger(process.env.MANUAL_RENDERER_MAX_PDF_BYTES, 30 * 1024 * 1024);
const MAX_DOCUMENT_HEIGHT = positiveInteger(process.env.MANUAL_RENDERER_MAX_DOCUMENT_HEIGHT, 30000);
const NAVIGATION_TIMEOUT_MS = positiveInteger(process.env.MANUAL_RENDERER_NAVIGATION_TIMEOUT_MS, 60000);
const TOKEN = String(process.env.MANUAL_RENDERER_TOKEN || "").trim();
const DESKTOP_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36";

let browserPromise = null;
let renderQueue = Promise.resolve();

function positiveInteger(value, fallback) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function isAllowedFeishuUrl(value) {
  try {
    const parsed = new URL(String(value || ""));
    const hostname = parsed.hostname.toLowerCase();
    return parsed.protocol === "https:"
      && !parsed.username
      && !parsed.password
      && (!parsed.port || parsed.port === "443")
      && (hostname === "feishu.cn" || hostname.endsWith(".feishu.cn"));
  } catch {
    return false;
  }
}

function tokenMatches(value) {
  const supplied = Buffer.from(String(value || ""));
  const expected = Buffer.from(TOKEN);
  return expected.length > 0
    && supplied.length === expected.length
    && crypto.timingSafeEqual(supplied, expected);
}

function jsonResponse(response, statusCode, payload) {
  const body = Buffer.from(JSON.stringify(payload));
  response.writeHead(statusCode, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": body.length,
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  });
  response.end(body);
}

function readJsonBody(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    request.on("data", (chunk) => {
      size += chunk.length;
      if (size > MAX_REQUEST_BYTES) {
        reject(new Error("请求内容过大"));
        request.destroy();
        return;
      }
      chunks.push(chunk);
    });
    request.on("end", () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}"));
      } catch {
        reject(new Error("请求格式错误"));
      }
    });
    request.on("error", reject);
  });
}

async function getBrowser() {
  if (!browserPromise) {
    browserPromise = chromium.launch({
      headless: true,
      args: ["--disable-dev-shm-usage", "--no-sandbox"],
    }).catch((error) => {
      browserPromise = null;
      throw error;
    });
  }
  const browser = await browserPromise;
  if (!browser.isConnected()) {
    browserPromise = null;
    return getBrowser();
  }
  return browser;
}

async function expandDocumentViewport(page) {
  for (let attempt = 0; attempt < 6; attempt += 1) {
    const requiredHeight = await page.locator(".bear-web-x-container").first().evaluate(
      (element) => element.scrollHeight + 64,
    );
    if (requiredHeight > MAX_DOCUMENT_HEIGHT) {
      throw new Error("飞书说明书内容过长，暂时无法生成预览");
    }
    const currentHeight = page.viewportSize()?.height || 0;
    if (requiredHeight <= currentHeight + 2) return;
    await page.setViewportSize({ width: 1280, height: requiredHeight });
    await page.waitForTimeout(1200);
  }
  const finalHeight = await page.locator(".bear-web-x-container").first().evaluate(
    (element) => element.scrollHeight + 64,
  );
  if (finalHeight > (page.viewportSize()?.height || 0) + 2) {
    throw new Error("飞书说明书未能完整展开");
  }
}

async function waitForDocumentImages(page) {
  await page.evaluate(async () => {
    const images = Array.from(document.images);
    await Promise.all(images.map((image) => {
      if (image.complete) return Promise.resolve();
      return new Promise((resolve) => {
        const done = () => resolve();
        image.addEventListener("load", done, { once: true });
        image.addEventListener("error", done, { once: true });
        setTimeout(done, 5000);
      });
    }));
  });
}

async function isolatePrintableDocument(page) {
  const textLength = await page.evaluate(() => {
    const editor = document.querySelector(".page-main > .page-main-item.editor");
    if (!editor) throw new Error("没有找到飞书说明书正文");
    const clone = editor.cloneNode(true);
    document.body.replaceChildren(clone);
    document.body.className = "";
    clone.style.cssText = [
      "position:static!important",
      "width:820px!important",
      "max-width:100%!important",
      "height:auto!important",
      "min-height:0!important",
      "margin:0 auto!important",
      "overflow:visible!important",
    ].join(";");
    return String(clone.innerText || "").trim().length;
  });
  if (textLength < 20) throw new Error("飞书说明书正文为空");
  await page.addStyleTag({
    content: `
      @page { size: A4; margin: 12mm 10mm; }
      html, body {
        width: 100% !important;
        height: auto !important;
        min-height: 0 !important;
        overflow: visible !important;
        position: static !important;
        background: #fff !important;
        margin: 0 !important;
        padding: 0 !important;
      }
      .page-main-item.editor, .editor-container, .docx-page-block {
        height: auto !important;
        min-height: 0 !important;
        max-height: none !important;
        overflow: visible !important;
      }
      #docx-drag-handle-container, .docx-block-menu { display: none !important; }
    `,
  });
}

async function renderFeishuPdf(url) {
  const browser = await getBrowser();
  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    userAgent: DESKTOP_USER_AGENT,
  });
  const page = await context.newPage();
  page.setDefaultNavigationTimeout(NAVIGATION_TIMEOUT_MS);
  page.setDefaultTimeout(NAVIGATION_TIMEOUT_MS);
  try {
    await page.goto(url, { waitUntil: "domcontentloaded" });
    // Feishu briefly mounts a second transition container while loading a wiki
    // document. The first container is the stable one used by its page layout.
    await page.locator(".bear-web-x-container").first().waitFor({ state: "visible" });
    await page.waitForFunction(() => {
      const editor = document.querySelector(".page-main > .page-main-item.editor");
      return Boolean(editor && String(editor.innerText || "").trim().length >= 20);
    });
    await page.waitForTimeout(2500);
    await expandDocumentViewport(page);
    await waitForDocumentImages(page);
    await isolatePrintableDocument(page);
    const pdf = await page.pdf({
      format: "A4",
      printBackground: true,
      preferCSSPageSize: true,
    });
    if (!pdf.subarray(0, 5).equals(Buffer.from("%PDF-")) || pdf.length > MAX_PDF_BYTES) {
      throw new Error("生成的说明书文件无效或过大");
    }
    return pdf;
  } finally {
    await context.close();
  }
}

function enqueueRender(operation) {
  const result = renderQueue.then(operation, operation);
  renderQueue = result.catch(() => undefined);
  return result;
}

async function handleRequest(request, response) {
  const requestUrl = new URL(request.url || "/", "http://renderer.local");
  if (request.method === "GET" && requestUrl.pathname === "/health") {
    jsonResponse(response, 200, { ok: true });
    return;
  }
  if (request.method !== "POST" || requestUrl.pathname !== "/render") {
    jsonResponse(response, 404, { ok: false, error: "接口不存在" });
    return;
  }
  if (!tokenMatches(request.headers["x-renderer-token"])) {
    jsonResponse(response, 403, { ok: false, error: "渲染服务凭据无效" });
    return;
  }
  let payload;
  try {
    payload = await readJsonBody(request);
  } catch (error) {
    jsonResponse(response, 400, { ok: false, error: error.message });
    return;
  }
  const url = String(payload.url || "").trim();
  if (!isAllowedFeishuUrl(url)) {
    jsonResponse(response, 400, { ok: false, error: "仅支持飞书 HTTPS 文档链接" });
    return;
  }
  try {
    const pdf = await enqueueRender(() => renderFeishuPdf(url));
    response.writeHead(200, {
      "Content-Type": "application/pdf",
      "Content-Length": pdf.length,
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    });
    response.end(pdf);
  } catch (error) {
    console.error("manual render failed", error);
    jsonResponse(response, 502, { ok: false, error: "飞书说明书暂时无法生成，请稍后重试" });
  }
}

function startServer() {
  if (!TOKEN) throw new Error("MANUAL_RENDERER_TOKEN is required");
  const server = http.createServer((request, response) => {
    handleRequest(request, response).catch((error) => {
      console.error("manual renderer request failed", error);
      if (!response.headersSent) {
        jsonResponse(response, 500, { ok: false, error: "说明书渲染服务异常" });
      } else {
        response.destroy();
      }
    });
  });
  server.requestTimeout = NAVIGATION_TIMEOUT_MS + 30000;
  server.listen(PORT, "0.0.0.0", () => {
    console.log(`manual renderer listening on ${PORT}`);
  });
  const shutdown = async () => {
    server.close();
    if (browserPromise) {
      try {
        const browser = await browserPromise;
        await browser.close();
      } catch {
        // The browser may already be gone during container shutdown.
      }
    }
  };
  process.once("SIGTERM", shutdown);
  process.once("SIGINT", shutdown);
  return server;
}

if (require.main === module) startServer();

module.exports = { isAllowedFeishuUrl, renderFeishuPdf, startServer };
