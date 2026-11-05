const configuredApiBase = String(import.meta.env.VITE_API_BASE_URL || "").trim();
export const API_BASE_URL = configuredApiBase || window.location.origin;
export const DING_CORP_ID = String(import.meta.env.VITE_DING_CORP_ID || "").trim();
