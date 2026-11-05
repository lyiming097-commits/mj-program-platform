export function companyKey(company) {
  for (const field of ["creditNo", "companyCode"]) {
    const value = (company[field] || "").trim().toUpperCase();
    if (value && !value.includes("*")) return `${field}:${value}`;
  }
  return JSON.stringify([company.companyName || "", company.legalPerson || "", company.establishDate || ""]);
}
