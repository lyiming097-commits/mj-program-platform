// Page-memory only: never persist financial data or reuse it across identities.
const FRESH_MS = 30_000;
const MAX_AGE_MS = 5 * 60_000;
const MAX_ENTRIES = 80;
const entries = new Map();
const pending = new Map();
let activeIdentity = "";
let generation = 0;

export function clearPresalesFeeCache() {
  generation += 1;
  entries.clear();
  pending.clear();
}

function cacheKey(identity, projectId, source) {
  const nextIdentity = String(identity || "");
  if (nextIdentity !== activeIdentity) {
    clearPresalesFeeCache();
    activeIdentity = nextIdentity;
  }
  return nextIdentity ? JSON.stringify([String(projectId), source]) : "";
}

export function readPresalesFeeCache(identity, projectId, source) {
  const key = cacheKey(identity, projectId, source);
  const entry = entries.get(key);
  if (!entry) return null;
  if (Date.now() - entry.loadedAt >= MAX_AGE_MS) {
    entries.delete(key);
    return null;
  }
  return { value: entry.value, fresh: Date.now() - entry.loadedAt < FRESH_MS };
}

export function loadPresalesFeeCache(identity, projectId, source, fetcher, { force = false } = {}) {
  const key = cacheKey(identity, projectId, source);
  const cached = readPresalesFeeCache(identity, projectId, source);
  if (!force && cached?.fresh) return Promise.resolve(cached.value);
  if (key && pending.has(key)) return pending.get(key);
  const requestGeneration = generation;
  const task = Promise.resolve().then(fetcher).then(value => {
    if (key && generation === requestGeneration) {
      entries.delete(key);
      entries.set(key, { value, loadedAt: Date.now() });
      while (entries.size > MAX_ENTRIES) entries.delete(entries.keys().next().value);
    }
    return value;
  }).catch(error => {
    if (generation === requestGeneration) {
      if ([401, 403, 404].includes(error?.status)) clearPresalesFeeCache();
      else entries.delete(key);
    }
    throw error;
  }).finally(() => {
    if (pending.get(key) === task) pending.delete(key);
  });
  if (key) pending.set(key, task);
  return task;
}
