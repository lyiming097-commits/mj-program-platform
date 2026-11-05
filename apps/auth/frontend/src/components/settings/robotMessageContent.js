import { sanitizeRichHtml } from "@platform-ui";

const placeholder =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5c8AAAAASUVORK5CYII=";
const imagePath =
  /^\/api\/org\/robot-messages\/public-images\/[a-f0-9-]{36}\/[A-Za-z0-9_-]{43}$/;
export function plainToHtml(text) {
  const element = document.createElement("div");
  element.textContent = String(text || "");
  return element.innerHTML.replace(/\n/g, "<br>");
}
export function messageHtml(html) {
  const source = document.createElement("template");
  source.innerHTML = String(html || "");
  const paths = [];
  source.content.querySelectorAll("img").forEach((image) => {
    const path = image.getAttribute("src") || "";
    if (!imagePath.test(path)) {
      image.remove();
      return;
    }
    paths.push(path);
    image.src = placeholder;
  });
  const clean = document.createElement("template");
  clean.innerHTML = sanitizeRichHtml(source.innerHTML);
  clean.content.querySelectorAll("img").forEach((image, index) => {
    image.setAttribute("src", paths[index]);
    image.setAttribute("alt", "消息图片");
    image.setAttribute("role", "button");
    image.setAttribute("tabindex", "0");
    image.setAttribute("aria-label", "查看图片原图");
  });
  return clean.innerHTML;
}
export function draftInfo(raw) {
  const html = sanitizeRichHtml(raw);
  const template = document.createElement("template");
  template.innerHTML = html;
  const images = [...template.content.querySelectorAll("img")];
  const bytes = images.reduce((total, image) => {
    const data = (image.getAttribute("src") || "").split(",")[1] || "";
    return (
      total +
      Math.floor((data.length * 3) / 4) -
      (data.endsWith("==") ? 2 : data.endsWith("=") ? 1 : 0)
    );
  }, 0);
  return {
    html,
    text: template.content.textContent.trim(),
    imageCount: images.length,
    imageBytes: bytes,
  };
}
