export const APP_PATH = "/";
export const CRM_PATH = "/crm";
export const CABLE_MALL_PATH = "/cable-mall";

const API_BASE_URL_RAW = (import.meta.env.VITE_API_BASE_URL || "").trim();

function normalizeConfigValue(raw) {
  const value = String(raw || "").trim();
  if (!value || /^\$[^$]+\$$/.test(value)) {
    return "";
  }
  return value;
}

function buildCurrentOriginUrl(candidate) {
  const currentUrl = new URL(window.location.href);
  const parsed = new URL(candidate);
  const raw = String(candidate || "").trim();
  const hasPath = /^https?:\/\/[^/?#]+\/[^?#]/i.test(raw);
  const path = hasPath ? parsed.pathname : "";
  return `${currentUrl.origin}${path}${parsed.search}${parsed.hash}`;
}

function resolveByHost(raw) {
  const normalized = normalizeConfigValue(raw);
  if (!normalized) {
    return null;
  }

  const candidates = normalized
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  if (!candidates.length) {
    return null;
  }

  const currentUrl = new URL(window.location.href);
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
      if (currentUrl.protocol === "https:" && parsed.host !== currentHost) {
        return buildCurrentOriginUrl(hostnameMatched);
      }
    } catch {
      return hostnameMatched;
    }
    return hostnameMatched;
  }

  return candidates[0] || null;
}

export const API_BASE_URL = resolveByHost(API_BASE_URL_RAW) || window.location.origin;
