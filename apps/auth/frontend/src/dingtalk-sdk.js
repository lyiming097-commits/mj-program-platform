const SDK_SCRIPTS = [
  {
    id: "dingtalk-login-sdk",
    src: "https://g.alicdn.com/dingding/h5-dingtalk-login/0.21.0/ddlogin.js",
    integrity: "sha384-XqmXFfAUI8FuvoBK2wMnsddUcxomgaAwgQplmDAfO83zARVNqMjiGnovVCszXmsf",
  },
  {
    id: "dingtalk-jsapi-sdk",
    src: "https://g.alicdn.com/dingding/dingtalk-jsapi/2.10.3/dingtalk.open.js",
    integrity: "sha384-AFiQLNEd6/dNLR14eCWZz9rXdQ8yaKFad664hIU7mkH77vpEY7he9D7zfBbUWNTa",
  },
  {
    id: "dingtalk-pc-sdk",
    src: "https://g.alicdn.com/dingding/dingtalk-pc-api/2.7.0/index.js",
    integrity: "sha384-J+AIIwGqfc/kfdsgBIDk/LdchFivOV/zRf5EUYGkH5Y2Pi5715+p9OkYa/SH4YRG",
  },
];

const loadingScripts = new Map();

function loadScript(definition) {
  if (loadingScripts.has(definition.id)) {
    return loadingScripts.get(definition.id);
  }
  const existing = document.getElementById(definition.id);
  if (existing?.dataset.loaded === "true") {
    return Promise.resolve();
  }

  const promise = new Promise((resolve, reject) => {
    const script = existing || document.createElement("script");
    script.id = definition.id;
    script.src = definition.src;
    script.integrity = definition.integrity;
    script.crossOrigin = "anonymous";
    script.referrerPolicy = "no-referrer";
    script.async = true;
    script.addEventListener("load", () => {
      script.dataset.loaded = "true";
      resolve();
    }, { once: true });
    script.addEventListener("error", () => {
      loadingScripts.delete(definition.id);
      reject(new Error(`钉钉安全组件加载失败：${definition.id}`));
    }, { once: true });
    if (!existing) {
      document.head.appendChild(script);
    }
  });
  loadingScripts.set(definition.id, promise);
  return promise;
}

export function ensureDingTalkRuntimeSdk() {
  return Promise.all(SDK_SCRIPTS.slice(1).map(loadScript));
}

export function ensureDingTalkLoginSdk() {
  return Promise.all(SDK_SCRIPTS.map(loadScript));
}
