export function splitParameterLines(value = "") {
  const source = String(value || "").trim();
  if (!source) return [];

  const separator = /\r?\n/.test(source) ? /\r?\n+/ : /[ \t]+\/[ \t]+|／/;
  return source
    .split(separator)
    .map((item) => item.trim())
    .filter(Boolean);
}
