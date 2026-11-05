const MANAGEMENT_ROLES = new Set(["sales", "service", "admin"]);
const SERVICE_PAGES = new Set(["rewards"]);
const COMMON_PAGES = new Set(["dashboard", "presales", "midsales", "aftersales", "collaboration", "settlements", "team", "suggestions"]);

export function managementCapabilities(access) {
  const roles = [access?.appPermission, ...(Array.isArray(access?.appPermissions) ? access.appPermissions : [])];
  const admitted = Boolean(access?.canManageApp && roles.some(role => MANAGEMENT_ROLES.has(role)));
  const settings = admitted && roles.includes("admin");
  const service = admitted && (settings || roles.includes("service"));
  return { admitted, settings, service };
}

export function managementPageAllowed(access, page) {
  const { admitted, settings, service } = managementCapabilities(access);
  if (!admitted) return false;
  if (page === "permissions") return settings;
  if (SERVICE_PAGES.has(page)) return service;
  return COMMON_PAGES.has(page);
}
