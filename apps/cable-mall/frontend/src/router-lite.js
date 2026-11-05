export const ROUTE_CHANGE_EVENT = "mj-program-route-change";
export const MOBILE_MENU_EVENT = "mj-program-toggle-mobile-menu";
export const MOBILE_HEADER_CONTEXT_EVENT = "mj-program-mobile-header-context";
export const MOBILE_BACK_REQUEST_EVENT = "mj-program-mobile-back-request";
export const MOBILE_CLOSE_PAGE_PICKERS_EVENT = "mj-program-mobile-close-page-pickers";
export const GLOBAL_FILTER_DISMISS_EVENT = "mj-program-global-filter-dismiss";

export function normalizePath(path) {
  const rawPath = String(path || window.location.pathname || "/").trim() || "/";
  try {
    const parsed = new URL(rawPath, window.location.origin);
    const normalized = parsed.pathname.replace(/\/+$/, "") || "/";
    return normalized;
  } catch {
    return rawPath.replace(/\/+$/, "") || "/";
  }
}

export function getCurrentPath() {
  return normalizePath(window.location.pathname);
}

function shouldHardNavigate(path) {
  return !(
    path === "/cable-mall" ||
    path.startsWith("/cable-mall/") ||
    path === "/external-cable-mall.html"
  );
}

export function navigateTo(path, options = {}) {
  const nextPath = normalizePath(path);
  if (shouldHardNavigate(nextPath)) {
    window.location.assign(nextPath);
    return;
  }
  const currentPath = getCurrentPath();
  if (nextPath === currentPath) {
    return;
  }

  const method = options.replace ? "replaceState" : "pushState";
  window.history[method]({}, "", nextPath);
  window.dispatchEvent(
    new CustomEvent(ROUTE_CHANGE_EVENT, {
      detail: { path: nextPath },
    }),
  );
}

export function navigateBack(fallbackPath = "/app") {
  if (requestMobileBack()) {
    return;
  }
  if (window.history.length > 1) {
    window.history.back();
    return;
  }
  navigateTo(fallbackPath, { replace: true });
}

export function requestMobileBack() {
  const event = new CustomEvent(MOBILE_BACK_REQUEST_EVENT, {
    cancelable: true,
    detail: { handled: false },
  });
  window.dispatchEvent(event);
  return event.defaultPrevented || Boolean(event.detail?.handled);
}

export function markMobileBackHandled(event) {
  if (!event) return;
  if (event.detail) {
    event.detail.handled = true;
  }
  event.preventDefault?.();
  event.stopImmediatePropagation?.();
}
