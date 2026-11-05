const status = document.getElementById('status');
const retry = document.getElementById('retry');

try {
  const url = new URL(decodeURIComponent(location.hash.slice(1)));
  if (url.protocol !== 'https:' || url.username || url.password) {
    throw new Error('Invalid manual URL');
  }
  retry.href = url.href;
  setTimeout(() => {
    status.textContent = '未能自动打开说明书，请点击下方链接重试。';
    retry.hidden = false;
  }, 8000);
  location.replace(url.href);
} catch {
  status.textContent = '说明书链接无效，无法打开。';
}
