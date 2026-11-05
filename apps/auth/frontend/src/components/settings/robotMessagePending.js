// Only submitted, unresolved requests are persisted; editor drafts stay in memory.
let database;
let tabId;
function scopedKey(identity) {
  if (!tabId) {
    tabId = sessionStorage.getItem("mj_robot_pending_tab");
    if (!tabId) {
      tabId = [...crypto.getRandomValues(new Uint8Array(16))]
        .map((n) => n.toString(16).padStart(2, "0"))
        .join("");
      sessionStorage.setItem("mj_robot_pending_tab", tabId);
    }
  }
  return `${identity}:${tabId}`;
}
function openDatabase() {
  if (!database)
    database = new Promise((resolve, reject) => {
      const request = indexedDB.open("mj_robot_message_pending", 1);
      request.onupgradeneeded = () =>
        request.result.createObjectStore("requests");
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error("无法打开待确认发送记录"));
    }).catch((error) => {
      database = null;
      throw error;
    });
  return database;
}
async function operate(identity, operation, payload) {
  const key = scopedKey(identity);
  const db = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(
      "requests",
      operation === "get" ? "readonly" : "readwrite",
    );
    const store = transaction.objectStore("requests");
    const request =
      operation === "put" ? store.put(payload, key) : store[operation](key);
    transaction.oncomplete = () => resolve(request.result);
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () =>
      reject(transaction.error || new Error("未能保存待确认发送记录"));
  });
}
export async function loadPending(identity) {
  let stored;
  try {
    stored = await operate(identity, "get");
  } catch {
    /* Older text requests can still recover. */
  }
  return stored || JSON.parse(sessionStorage.getItem(identity) || "null");
}
export async function storePending(identity, payload) {
  // A recovered Vue ref contains proxies; IndexedDB requires plain values.
  await operate(identity, "put", JSON.parse(JSON.stringify(payload)));
  sessionStorage.removeItem(identity);
}
export async function clearPending(identity) {
  sessionStorage.removeItem(identity);
  await operate(identity, "delete");
}
