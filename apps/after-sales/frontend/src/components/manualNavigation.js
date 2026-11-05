export function manualNavigation(value, { origin, userAgent = "", platform = "", portalEmbedded = false, portalDingTalk = false }) {
  const raw = String(value || "").trim();
  if (!raw || raw.startsWith("//")) return null;
  let target;
  try {
    target = new URL(raw, origin);
  } catch {
    return null;
  }
  if (target.username || target.password) return null;
  if (target.protocol !== "https:" && !(target.protocol === "http:" && target.origin === origin)) return null;

  const client = String(platform || "").toLowerCase();
  const mobile = /android|iphone|ipad|ipod|mobile|harmonyos/i.test(userAgent);
  const desktopDingTalk = portalDingTalk || (!mobile && (
    client === "pc" || (!client && /dingtalk/i.test(userAgent) && /windows|macintosh|mac os x/i.test(userAgent))
  ));
  const mobileDingTalk = !desktopDingTalk && (["ios", "android"].includes(client) || (!client && mobile && /dingtalk/i.test(userAgent)));
  if (desktopDingTalk || mobileDingTalk) {
    // DingTalk openLink may launch the system browser; AppLink targets its workbench.
    const link = new URL("https://applink.dingtalk.com/page/link");
    const feishu = ["feishu.cn", "feishu.net", "feishu.com", "larksuite.com"]
      .some((domain) => target.hostname === domain || target.hostname.endsWith(`.${domain}`));
    const needsWorkbenchRedirect = desktopDingTalk && !mobile && !feishu && target.protocol === "https:" && origin && target.origin !== origin;
    const destination = needsWorkbenchRedirect
      ? new URL(`/after-sales/open-manual.html#${encodeURIComponent(target.href)}`, origin).href
      : target.href;
    link.searchParams.set("url", destination);
    if (desktopDingTalk) link.searchParams.set("targetDesktop", "workbench");
    else link.searchParams.set("target", "fullScreen");
    return { href: link.href, ...(portalEmbedded ? { target: "_top" } : {}) };
  }
  return { href: target.href, target: "_blank", rel: "noopener noreferrer" };
}
