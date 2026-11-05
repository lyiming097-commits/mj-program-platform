import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { runInNewContext } from "node:vm";
import { manualNavigation } from "../src/components/manualNavigation.js";

function component(name) {
  return readFileSync(new URL(`../src/components/${name}.vue`, import.meta.url), "utf8");
}

test("linked products open full details at level two in both project workflows", () => {
  const panel = component("RelatedProductsPanel");
  const workspace = component("ProjectWorkspace");
  const detail = component("RelatedProductDetailDrawer");
  const picker = component("RelatedProductPicker");

  assert.match(panel, /<button[^>]+aria-haspopup="dialog"[^>]+@click="emit\('open', product\)"/);
  assert.equal((workspace.match(/@open="openRelatedProductDetail"/g) || []).length, 2);
  assert.match(workspace, /getProductCatalogItem\(productId\)/);
  assert.match(workspace, /<RelatedProductDetailDrawer\s+:open="relatedProductDetailOpen && drawerOpen"[\s\S]+?:level="2"/);
  assert.match(workspace, /@retry="loadRelatedProductDetail"/);
  assert.match(detail, /level: \{ type: Number, default: 3 \}/);
  assert.match(picker, /<RelatedProductDetailDrawer\s+:open="Boolean\(detailProduct\)"/);
});

test("product manuals keep original links without a PDF preview", () => {
  const detail = component("RelatedProductDetailDrawer");
  assert.match(detail, /<a v-if="manual\.navigation" :href="manual\.navigation\.href" :target="manual\.navigation\.target"/);
  assert.match(detail, /portalEmbedded: window\.frameElement\?\.dataset\.portalEmbed === "true"/);
  assert.match(detail, /portalDingTalk: window\.frameElement\?\.dataset\.portalDingtalk === "true"/);
  assert.doesNotMatch(detail, /@click="delegateManualToPortal/);
  assert.doesNotMatch(detail, /openManual\(|PdfCanvasViewer|manual\/\$\{manual\.key\}\/preview/);
});

test("DingTalk desktop opens the original Feishu link in a workbench page", () => {
  const origin = "https://oa.hzmaijie.com";
  for (const original of ["https://tenant.feishu.cn/wiki/example?x=1&y=%E8%AF%B4%E6%98%8E", "https://docs.larksuite.com/wiki/1"]) {
    const navigation = manualNavigation(original, { origin, platform: "pc" });
    const link = new URL(navigation.href);
    assert.equal(`${link.origin}${link.pathname}`, "https://applink.dingtalk.com/page/link");
    assert.equal(link.searchParams.get("url"), original);
    assert.equal(link.searchParams.get("targetDesktop"), "workbench");
    assert.equal(navigation.target, undefined);
    assert.equal(manualNavigation(original, { origin, userAgent: "DingTalk Windows" }).href, navigation.href);
  }
});

test("DingTalk desktop opens non-Feishu HTTPS links from an in-workbench redirect", () => {
  const origin = "https://oa.hzmaijie.com";
  for (const original of [
    "https://alidocs.dingtalk.com/i/nodes/Mk5evdR04jBV596qanB3VQL3x2OlParn?utm_scene=team_space",
    "https://vendor.example.com/docs/manual.pdf?lang=zh&version=2",
    "https://feishu.cn.evil.example/manual",
  ]) {
    const navigation = manualNavigation(original, { origin, portalEmbedded: true, portalDingTalk: true });
    const link = new URL(navigation.href);
    const bridge = new URL(link.searchParams.get("url"));
    assert.equal(`${link.origin}${link.pathname}`, "https://applink.dingtalk.com/page/link");
    assert.equal(link.searchParams.get("targetDesktop"), "workbench");
    assert.equal(`${bridge.origin}${bridge.pathname}`, `${origin}/after-sales/open-manual.html`);
    assert.equal(decodeURIComponent(bridge.hash.slice(1)), original);
    assert.equal(navigation.target, "_top");
  }
  const internal = `${origin}/after-sales/files/manual.pdf`;
  assert.equal(new URL(manualNavigation(internal, { origin, platform: "pc" }).href).searchParams.get("url"), internal);
  const mobile = manualNavigation("https://alidocs.dingtalk.com/i/nodes/1", { origin, platform: "ios", userAgent: "DingTalk iPhone" });
  const mobileLink = new URL(mobile.href);
  assert.equal(mobileLink.searchParams.get("url"), "https://alidocs.dingtalk.com/i/nodes/1");
  assert.equal(mobileLink.searchParams.get("target"), "fullScreen");
});

test("manual bridge uses CSP-allowed external script and rejects unsafe destinations", () => {
  const html = readFileSync(new URL("../public/open-manual.html", import.meta.url), "utf8");
  const nginx = readFileSync(new URL("../nginx.conf", import.meta.url), "utf8");
  const script = readFileSync(new URL("../public/open-manual.js", import.meta.url), "utf8");
  assert.match(html, /<script defer src="\/after-sales\/open-manual\.js"><\/script>/);
  assert.doesNotMatch(html, /<script\s*>/);
  assert.match(nginx, /location = \/after-sales\/open-manual\.html \{[\s\S]*?try_files \/open-manual\.html =404;/);
  assert.match(nginx, /location = \/after-sales\/open-manual\.js \{[\s\S]*?try_files \/open-manual\.js =404;/);
  const run = (hash) => {
    const redirects = [];
    const status = { textContent: "" };
    const retry = { hidden: true, href: "" };
    const timers = [];
    runInNewContext(script, {
      URL, decodeURIComponent,
      location: { hash, replace: (url) => redirects.push(url) },
      document: { getElementById: (id) => id === "status" ? status : retry },
      setTimeout: (callback) => timers.push(callback),
    });
    return { redirects, status, retry, timers };
  };
  const doc = "https://alidocs.dingtalk.com/i/nodes/1?utm_scene=team_space";
  const valid = run(`#${encodeURIComponent(doc)}`);
  assert.deepEqual(valid.redirects, [doc]);
  assert.equal(valid.retry.href, doc);
  valid.timers[0]();
  assert.match(valid.status.textContent, /未能自动打开/);
  assert.equal(valid.retry.hidden, false);
  for (const invalid of ["", "javascript:alert(1)", "http://vendor.example.com/doc", "https://user@vendor.example.com/doc"]) {
    const result = run(`#${encodeURIComponent(invalid)}`);
    assert.deepEqual(result.redirects, []);
    assert.match(result.status.textContent, /链接无效/);
    assert.equal(result.retry.hidden, true);
  }
});

test("ordinary browsers retain native external links and invalid URLs are rejected", () => {
  const options = { origin: "https://oa.hzmaijie.com" };
  for (const url of ["https://example.com/help", "https://tenant.feishu.cn/wiki/1", "https://example.com/manual.pdf"]) {
    assert.deepEqual(manualNavigation(url, options), { href: url, target: "_blank", rel: "noopener noreferrer" });
  }
  assert.equal(manualNavigation("javascript:alert(1)", options), null);
  assert.equal(manualNavigation("//other.example/manual", options), null);
  assert.equal(manualNavigation("http://other.example/manual", options), null);
});

test("portal DingTalk links navigate from the top-level browsing context", () => {
  const original = "https://tenant.feishu.cn/wiki/example";
  const origin = "https://oa.hzmaijie.com";
  const embedded = manualNavigation(original, { origin, platform: "notInDingTalk", portalEmbedded: true, portalDingTalk: true });
  const link = new URL(embedded.href);
  assert.equal(link.hostname, "applink.dingtalk.com");
  assert.equal(link.searchParams.get("url"), original);
  assert.equal(link.searchParams.get("targetDesktop"), "workbench");
  assert.equal(embedded.target, "_top");
  assert.equal(embedded.rel, undefined);
  assert.deepEqual(manualNavigation(original, { origin, platform: "notInDingTalk", portalEmbedded: true }), {
    href: original, target: "_blank", rel: "noopener noreferrer",
  });
  assert.equal(manualNavigation("javascript:alert(1)", { origin, portalEmbedded: true, portalDingTalk: true }), null);
});
