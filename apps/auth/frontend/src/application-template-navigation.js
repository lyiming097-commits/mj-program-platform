// Match Portal's existing app-opening bridge; only Portal owns its workspace tabs.
let templateRequestId = 0;
export function openApplicationTemplateTab(event) {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return null;
  let frame;
  try { frame = window.frameElement; } catch { return null; }
  if (!frame?.hasAttribute("data-portal-embed")) return null;
  event.preventDefault();
  const requestId = `auth-template-${Date.now()}-${++templateRequestId}`;
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => onReply(false, "平台未响应，请刷新平台页面后重试"), 10000);
    function onReply(ok, message = "") {
      window.clearTimeout(timer);
      window.removeEventListener("message", onResult);
      if (ok) resolve();
      else reject(new Error(message || "无法打开应用模板"));
    }
    function onResult(message) {
      if (message.origin !== window.location.origin || message.source !== window.parent
        || message.data?.type !== "mj.portal.app.open.result" || message.data?.requestId !== requestId) return;
      onReply(message.data.ok, message.data.message);
    }
    window.addEventListener("message", onResult);
    let handled = false;
    try {
      handled = !frame.dispatchEvent(new CustomEvent("mj.portal.app.open", {
        bubbles: true, cancelable: true,
        detail: { appId: "starter-app", reply: onReply },
      }));
    } catch { /* The message channel also works with a Portal embed. */ }
    if (!handled) window.parent.postMessage({ type: "mj.portal.app.open", appId: "starter-app", requestId }, window.location.origin);
  });
}
