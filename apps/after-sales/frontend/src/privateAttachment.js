export function isPdfAttachment(item) {
  const mimeType = String(item?.mimeType || item?.contentType || "").toLowerCase();
  return mimeType === "application/pdf" || /\.pdf$/i.test(String(item?.originalName || ""));
}

export async function fetchPrivateAttachment(item, apiFetchRaw, timeoutMs = 600_000) {
  const response = await apiFetchRaw(item.downloadUrl, {}, null, { timeoutMs });
  return response.blob();
}

export function downloadPrivateAttachment(blob, filename, {
  documentRef = document,
  urlApi = URL,
  schedule = setTimeout,
} = {}) {
  const objectUrl = urlApi.createObjectURL(blob);
  try {
    const link = documentRef.createElement("a");
    link.href = objectUrl;
    link.download = filename || "附件";
    documentRef.body.appendChild(link);
    try { link.click(); } finally { link.remove(); }
  } catch (error) {
    urlApi.revokeObjectURL(objectUrl);
    throw error;
  }
  schedule(() => urlApi.revokeObjectURL(objectUrl), 60_000);
}
