export const ROUND_SHARE_API = "biz.util.share";

export function presalesRoundLink({ origin, projectId, nodeKey, roundId }) {
  if (!projectId || !nodeKey || !roundId) throw new Error("轮次尚未保存，请稍后重试");
  const url = new URL("/after-sales/presales/", origin);
  url.searchParams.set("projectId", String(projectId));
  url.searchParams.set("nodeKey", nodeKey);
  url.searchParams.set("roundId", roundId);
  return url.href;
}

export function presalesRoundCard({ origin, projectId, projectName, nodeKey, nodeName, roundId, roundIndex }) {
  const pageUrl = presalesRoundLink({ origin, projectId, nodeKey, roundId });
  const link = new URL("https://applink.dingtalk.com/page/link");
  link.searchParams.set("url", pageUrl);
  link.searchParams.set("targetDesktop", "workbench");
  link.searchParams.set("target", "fullScreen");
  return {
    type: 0, url: link.href,
    title: `${projectName} · ${nodeName} · 第${roundIndex + 1}轮`,
    content: "打开项目查看本轮附件、备注和商城方案，可通过或填写原因后新增一轮。",
    image: new URL("/after-sales/round-share.png", origin).href,
    pageUrl,
  };
}

function sdkMessage(reason) {
  return String(reason?.errorMessage || reason?.errMsg || reason?.message || reason || "未知错误");
}

export function createRoundSharer({ windowObject = window, getConfig } = {}) {
  let readyFor = "";
  let configuring = null;
  function runtime() {
    return [windowObject.dd, windowObject.DingTalkPC]
      .find(sdk => sdk?.biz?.util?.share && sdk.env?.platform !== "notInDingTalk") || null;
  }
  function available() {
    const platform = runtime()?.env?.platform;
    return Boolean(runtime() && (platform || /dingtalk/i.test(windowObject.navigator?.userAgent || "")));
  }
  async function configure(sdk) {
    const url = windowObject.location.href.split("#")[0];
    if (readyFor === url) return;
    if (configuring) await configuring;
    if (readyFor === url) return;
    configuring = (async () => {
      const response = await getConfig(url, ROUND_SHARE_API);
      const config = response?.data || response;
      if (!config?.signature || !config?.corpId || typeof sdk.config !== "function") {
        throw new Error("钉钉转发授权不可用，请稍后重试");
      }
      await new Promise((resolve, reject) => {
        let settled = false;
        const finish = (reason) => {
          if (settled) return;
          settled = true;
          windowObject.clearTimeout(timer);
          if (reason) reject(new Error(`钉钉转发授权失败：${sdkMessage(reason)}`));
          else resolve();
        };
        const timer = windowObject.setTimeout(() => finish("授权超时"), 12000);
        sdk.error?.(reason => finish(reason));
        try {
          sdk.config({ ...config, jsApiList: [ROUND_SHARE_API] });
          sdk.ready(() => finish());
        } catch (reason) { finish(reason); }
      });
      readyFor = url;
    })();
    try { await configuring; } finally { configuring = null; }
  }
  async function share(card) {
    if (!available()) return { status: "unsupported" };
    const sdk = runtime();
    await configure(sdk);
    return new Promise((resolve, reject) => {
      let settled = false;
      const finish = (reason, result) => {
        if (settled) return;
        settled = true;
        windowObject.clearTimeout(timer);
        const message = sdkMessage(reason);
        if (reason && /cancel|取消/i.test(message)) resolve({ status: "cancelled" });
        else if (reason) reject(new Error(`钉钉转发失败：${message}`));
        else resolve({ status: "shared", result });
      };
      const timer = windowObject.setTimeout(() => finish("钉钉未返回转发结果，请先在聊天中确认是否发送"), 120000);
      const { pageUrl, ...payload } = card;
      try {
        sdk.biz.util.share({ ...payload, onSuccess: result => finish(null, result), onFail: reason => finish(reason) });
      } catch (reason) { finish(reason); }
    });
  }
  return { available, share };
}
