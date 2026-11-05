import assert from "node:assert/strict";
import test from "node:test";
import { createRoundSharer, presalesRoundCard, ROUND_SHARE_API } from "../src/components/presalesRoundForward.js";

function environment(behavior = "success") {
  let ready;
  const calls = [];
  const sdk = {
    env: { platform: "pc" },
    config: value => calls.push({ config: value }),
    ready: callback => { ready = callback; queueMicrotask(callback); },
    error: () => {},
    biz: { util: { share: payload => {
      calls.push({ payload });
      if (behavior === "cancel") payload.onFail({ errorMessage: "user cancel" });
      else if (behavior === "failure") payload.onFail({ errMsg: "permission denied" });
      else payload.onSuccess({});
    } } },
  };
  const windowObject = { dd: sdk, location: { href: "https://platform.example/after-sales/presales/?projectId=7" },
    navigator: { userAgent: "DingTalk" }, setTimeout, clearTimeout };
  return { windowObject, calls, sdk };
}
const card = presalesRoundCard({ origin: "https://platform.example", projectId: 7, projectName: "学校项目",
  nodeKey: "early-plan", nodeName: "前期方案", roundId: "stable-round-2", roundIndex: 1 });

test("card opens the existing project at a stable round without credentials or draft content", () => {
  const appLink = new URL(card.url);
  assert.equal(appLink.hostname, "applink.dingtalk.com");
  assert.equal(appLink.searchParams.get("targetDesktop"), "workbench");
  const target = new URL(appLink.searchParams.get("url"));
  assert.equal(target.pathname, "/after-sales/presales/");
  assert.deepEqual(Object.fromEntries(target.searchParams), { projectId: "7", nodeKey: "early-plan", roundId: "stable-round-2" });
  assert.equal(card.title, "学校项目 · 前期方案 · 第2轮");
});

test("native sharing signs the current URL and reports success only after the SDK callback", async () => {
  const env = environment();
  const configs = [];
  const sharer = createRoundSharer({ windowObject: env.windowObject, getConfig: async (url, api) => {
    configs.push({ url, api });
    return { corpId: "corp", agentId: "agent", signature: "test-signature", nonceStr: "nonce", timeStamp: 123 };
  } });
  assert.equal((await sharer.share(card)).status, "shared");
  assert.equal(configs[0].url, env.windowObject.location.href);
  assert.equal(configs[0].api, ROUND_SHARE_API);
  assert.deepEqual(env.calls[0].config.jsApiList, [ROUND_SHARE_API]);
  assert.equal(env.calls[1].payload.url, card.url);
  assert.equal("pageUrl" in env.calls[1].payload, false);
  await sharer.share(card);
  assert.equal(configs.length, 1);
  env.windowObject.location.href += "&roundId=changed";
  await sharer.share(card);
  assert.equal(configs.length, 2);
});

test("cancel, failures and ordinary browsers never report a sent message", async () => {
  const config = async () => ({ corpId: "corp", signature: "signed" });
  const cancelled = createRoundSharer({ ...environment("cancel"), getConfig: config });
  assert.equal((await cancelled.share(card)).status, "cancelled");
  const failed = createRoundSharer({ ...environment("failure"), getConfig: config });
  await assert.rejects(failed.share(card), /转发失败.*permission denied/);
  const badConfig = createRoundSharer({ ...environment(), getConfig: async () => { throw new Error("授权服务不可用"); } });
  await assert.rejects(badConfig.share(card), /授权服务不可用/);
  const unsupported = createRoundSharer({ windowObject: { navigator: {}, dd: { env: { platform: "notInDingTalk" } } },
    getConfig: () => assert.fail("ordinary browser must not request native authorization") });
  assert.equal((await unsupported.share(card)).status, "unsupported");
});
