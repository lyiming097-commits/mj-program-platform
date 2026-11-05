export const RESULT_PATH = "/auth/result";
export const APP_PATH = "/";
export const AUTH_LOGIN_PATH = "/auth";
export const SETTINGS_ORGANIZATION_PATH = "/auth/settings/organization";
export const SETTINGS_ENABLED_DEPARTMENTS_PATH = "/auth/settings/enabled-departments";
export const SETTINGS_ORGANIZATION_PERMISSIONS_PATH = "/auth/settings/permissions";
export const SETTINGS_HANDOVER_PATH = "/auth/settings/handover";
export const SETTINGS_COMPANY_ENTITIES_PATH = "/auth/settings/company-entities";
export const SETTINGS_ROBOT_MESSAGES_PATH = "/auth/settings/robot-messages";
export const SETTINGS_NOTIFICATIONS_PATH = "/auth/settings/notifications";
export const SETTINGS_BUSINESS_REGISTRY_PATH = "/auth/settings/business-registry";
export const SETTINGS_ADMINISTRATIVE_REGIONS_PATH = "/auth/settings/regions";
export const SETTINGS_APPLICATION_TEMPLATE_PATH = "/auth/settings/application-template";
export const APPLICATION_TEMPLATE_PATH = "/starter-app/";
export const APPLICATION_TEMPLATE_WORKSPACE_PATH = "/?app=starter-app";
export const SETTINGS_COMPANY_ENTITIES_LEAVE_EVENT = "mj-auth-company-entities-request-leave";
const API_BASE_URL_RAW = (import.meta.env.VITE_API_BASE_URL || "").trim();
const currentUrl = new URL(window.location.href);
const currentSearchParams = currentUrl.searchParams;

function normalizeConfigValue(raw) {
  const value = String(raw || "").trim();
  if (!value || /^\$[^$]+\$$/.test(value)) {
    return "";
  }
  return value;
}

function buildCurrentOriginUrl(candidate) {
  const parsed = new URL(candidate);
  const raw = String(candidate || "").trim();
  const hasPath = /^https?:\/\/[^/?#]+\/[^?#]/i.test(raw);
  const path = hasPath ? parsed.pathname : "";
  return `${currentUrl.origin}${path}${parsed.search}${parsed.hash}`;
}

export const DING_CLIENT_ID = normalizeConfigValue(import.meta.env.VITE_DING_CLIENT_ID || "");
export const DING_CORP_ID =
  normalizeConfigValue(currentSearchParams.get("corpId")) ||
  normalizeConfigValue(import.meta.env.VITE_DING_CORP_ID || "");
const DING_REDIRECT_URI = (import.meta.env.VITE_DING_REDIRECT_URI || "").trim();
export const DING_SCOPE = DING_CORP_ID ? "openid corpid" : "openid";
const CURRENT_REDIRECT_URI = `${window.location.origin}${RESULT_PATH}`;

function resolveByHost(raw) {
  if (!raw) {
    return null;
  }
  const candidates = raw
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  if (!candidates.length) {
    return null;
  }

  const currentHost = window.location.host;
  const currentHostname = window.location.hostname;
  const currentProtocol = window.location.protocol;
  const matched = candidates.find((item) => {
    try {
      const parsed = new URL(item);
      return parsed.host === currentHost && parsed.protocol === currentProtocol;
    } catch {
      return false;
    }
  });
  if (matched) {
    return matched;
  }

  const hostnameMatched = candidates.find((item) => {
    try {
      const parsed = new URL(item);
      return parsed.hostname === currentHostname && parsed.protocol === currentProtocol;
    } catch {
      return false;
    }
  });
  if (hostnameMatched) {
    try {
      const parsed = new URL(hostnameMatched);
      if (currentProtocol === "https:" && parsed.host !== currentHost) {
        return buildCurrentOriginUrl(hostnameMatched);
      }
    } catch {
      return hostnameMatched;
    }
    return hostnameMatched;
  }

  if (currentProtocol === "https:") {
    const insecureSameHost = candidates.find((item) => {
      try {
        const parsed = new URL(item);
        return parsed.hostname === currentHostname && parsed.protocol === "http:";
      } catch {
        return false;
      }
    });
    if (insecureSameHost) {
      return buildCurrentOriginUrl(insecureSameHost);
    }
  }

  return candidates[0] || null;
}

export const REDIRECT_URI = resolveByHost(DING_REDIRECT_URI) || CURRENT_REDIRECT_URI;
export const API_BASE_URL = resolveByHost(API_BASE_URL_RAW) || window.location.origin;
export const DING_VIEW_SIZE = 240;
export const DING_WIDGET_SIZE = 300;

function parseBooleanConfig(value) {
  const normalizedValue = normalizeConfigValue(value).toLowerCase();
  if (["1", "true", "yes", "y", "on"].includes(normalizedValue)) {
    return true;
  }
  if (["0", "false", "no", "n", "off"].includes(normalizedValue)) {
    return false;
  }
  return null;
}

const localDevHostnames = new Set(["localhost", "127.0.0.1", "::1"]);
const authDevLoginConfig = parseBooleanConfig(import.meta.env.VITE_AUTH_DEV_LOGIN || "");
export const AUTH_DEV_LOGIN_ENABLED =
  authDevLoginConfig ?? localDevHostnames.has(window.location.hostname.toLowerCase());
