export function collectionRows(payload) {
  if (Array.isArray(payload)) return payload;
  for (const key of ["results", "items", "data"]) {
    if (Array.isArray(payload?.[key])) return payload[key];
  }
  return [];
}

// Directory selectors and local multi-column filters require the complete
// permitted collection. Respect the server's page size instead of requesting
// an oversized first page and silently losing the remaining records.
export async function allCollectionRows(fetchPage, params = {}) {
  const first = await fetchPage({ ...params, page: 1, page_size: 100 });
  const rows = [...collectionRows(first)];
  const pages = Math.max(1, Number(first?.totalPages) || 1);
  for (let page = 2; page <= pages; page += 3) {
    const batch = await Promise.all(Array.from({ length: Math.min(3, pages - page + 1) }, (_, offset) => (
      fetchPage({ ...params, page: page + offset, page_size: 100 })
    )));
    rows.push(...batch.flatMap(collectionRows));
  }
  return [...new Map(rows.map((row, index) => [row.id ?? `row-${index}`, row])).values()];
}
