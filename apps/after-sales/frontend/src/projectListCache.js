const STORAGE_KEY = "mj-after-sales:presales-pages:v2";
const MAX_PAGES = 12;

export function projectListIdentity(session) {
  if (!session?.sessionId || !session?.userId) return "";
  // Reuse the same user's verified page after re-login, like Mall. Session
  // validation and in-flight response isolation remain separate requirements.
  return JSON.stringify([session.userId, session.actorUserId || session.userId, Boolean(session.isProxying), Boolean(session.canUseSystemAdmin),
    Boolean(session.canManageApp), session.appPermission || "", Boolean(session.canManageBusiness),
    Boolean(session.canManageSettlements), Boolean(session.canManageService), (Array.isArray(session.appPermissions) ? [...session.appPermissions].sort() : [])]);
}

function queryKey(params) {
  return JSON.stringify(Object.entries(params).filter(([key]) => key !== "crmRefresh")
    .sort(([a], [b]) => a.localeCompare(b)));
}

function read(identity) {
  try {
    const value = JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) || "null");
    return value?.identity === identity && Array.isArray(value.pages) ? value.pages : [];
  } catch { return []; }
}

export function readProjectListCache(identity, params) {
  if (!identity) return null;
  const entry = read(identity).find((item) => item.key === queryKey(params));
  return entry && entry.expiresAt > Date.now() ? entry.response : null;
}

export function writeProjectListCache(identity, params, response) {
  if (!identity) return;
  const expiresAt = Date.parse(response.crmScopeExpiresAt || "");
  // Display caches never outlive the backend's verified visibility scope.
  // A denied/expired scope discards every saved query, not just this page.
  if (response.crmScopeReady !== true || !(expiresAt > Date.now())) {
    clearProjectListCache();
    return;
  }
  const key = queryKey(params);
  const pages = read(identity).filter((entry) => entry.key !== key && entry.expiresAt > Date.now());
  pages.push({ key, expiresAt, response });
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ identity, pages: pages.slice(-MAX_PAGES) }));
  } catch { /* Storage limits must not block a successful network response. */ }
}

export function clearProjectListCache() {
  try { window.sessionStorage.removeItem(STORAGE_KEY); } catch {}
}

export const CRM_SYNC_POLL_DELAYS = Object.freeze([900, 1800, 3200, 5000]);
