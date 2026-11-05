import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = createRequire(new URL("../package.json", import.meta.url));
const browserTools = createRequire(new URL("../../../../.codex-artifacts/package.json", import.meta.url));
const { chromium, devices } = browserTools("playwright");
const { createServer } = await import(frontend.resolve("vite"));
const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const staleSession = { sessionId: "expired-session", userId: "fixture-user", actorUserId: "fixture-user" };

test("public auth pages complete login without requesting authenticated notifications", async (t) => {
  const server = process.env.AUTH_NOTIFICATION_ISOLATION_BASE_URL ? null : await createServer({
    root: frontendRoot,
    define: { "import.meta.env.VITE_AUTH_DEV_LOGIN": JSON.stringify("false") },
    server: { host: "127.0.0.1", port: 5612, strictPort: true },
  });
  await server?.listen();
  const browser = await chromium.launch({ headless: true });
  const origin = process.env.AUTH_NOTIFICATION_ISOLATION_BASE_URL || `http://127.0.0.1:${server.httpServer.address().port}`;
  try {
    for (const scenario of [
      { name: "mobile login with no session", path: "/auth/?corpId=fixture-corp", mobile: true },
      { name: "mobile login with expired session", path: "/auth/?corpId=fixture-corp", mobile: true, stale: true },
      { name: "mobile login from the previous error URL", path: "/auth/?corpId=fixture-corp&error=Missing+auth+token", mobile: true, stale: true },
      { name: "mobile workbench callback with expired session", path: "/auth/result?loginType=workbench&code=fixture-code", mobile: true, stale: true, callback: true },
      { name: "desktop scan callback with expired session", path: "/auth/result?code=fixture-code&state=fixture-state", stale: true, callback: true },
    ]) {
      await t.test(scenario.name, async () => {
        const context = await browser.newContext(scenario.mobile ? {
          ...devices["iPhone 13"],
          userAgent: `${devices["iPhone 13"].userAgent} DingTalk/7.6.0`,
        } : { viewport: { width: 1440, height: 960 } });
        try {
          await context.addInitScript(({ stale, session }) => {
            if (stale) sessionStorage.setItem("mj_program_login_session", JSON.stringify(session));
            sessionStorage.setItem("mj_program_ding_oauth_state", "fixture-state");
            window.dd = {
              env: { platform: "ios" },
              config() {},
              ready(callback) { callback(); },
              error() {},
              runtime: { permission: { requestAuthCode(options) {
                window.releaseFixtureAuthCode = () => options.onSuccess({ code: "fixture-code" });
              } } },
            };
            // Keep the third-party bridge simulated; the real Auth app and API
            // client still run, including their handling of expired sessions.
            const installSdkMarkers = () => {
              if (!document.head) return;
              observer.disconnect();
              for (const id of ["dingtalk-login-sdk", "dingtalk-jsapi-sdk", "dingtalk-pc-sdk"]) {
                const script = document.createElement("script");
                script.id = id;
                script.dataset.loaded = "true";
                document.head.appendChild(script);
              }
            };
            const observer = new MutationObserver(installSdkMarkers);
            observer.observe(document, { childList: true, subtree: true });
            installSdkMarkers();
          }, { stale: scenario.stale, session: staleSession });
          const requests = [];
          const exchanges = [];
          await context.route("**/api/**", async (route) => {
            const path = new URL(route.request().url()).pathname;
            requests.push(path);
            const fulfill = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
            if (path === "/api/auth/session/validate" || path === "/api/org/notices/unread") {
              return fulfill({ error: "Missing auth token" }, 401);
            }
            if (path === "/api/dingtalk/jsapi_config") return fulfill({ corpId: "fixture-corp", jsApiList: ["runtime.permission.requestAuthCode"] });
            if (path === "/api/auth/code") {
              exchanges.push(route.request().postDataJSON());
              await new Promise((resolve) => setTimeout(resolve, 500));
              return fulfill({ ...staleSession, sessionId: "fresh-session" });
            }
            return fulfill({ error: `Unexpected API: ${path}` }, 500);
          });
          await context.route(`${origin}/`, (route) => route.fulfill({ contentType: "text/html", body: "<h1>Portal fixture</h1>" }));
          const page = await context.newPage();
          const pageErrors = [];
          const documents = [];
          page.on("pageerror", (error) => pageErrors.push(error.message));
          page.on("request", (request) => {
            if (request.isNavigationRequest() && request.frame() === page.mainFrame()) documents.push(request.url());
          });
          await page.goto(`${origin}${scenario.path}`);
          if (!scenario.callback) {
            await page.waitForFunction(() => typeof window.releaseFixtureAuthCode === "function", null, { timeout: 8000 }).catch(async (error) => {
              throw new Error(`${error.message}; URL=${page.url()}; requests=${JSON.stringify(requests)}; errors=${JSON.stringify(pageErrors)}; body=${(await page.locator("body").innerText()).slice(0, 1000)}`);
            });
            await page.evaluate(() => {
              window.dispatchEvent(new Event("focus"));
              window.dispatchEvent(new Event("pageshow"));
              document.dispatchEvent(new Event("visibilitychange"));
              window.releaseFixtureAuthCode();
            });
          }
          await page.getByRole("heading", { name: "Portal fixture" }).waitFor({ timeout: 8000 });
          assert.equal(requests.filter((path) => path === "/api/org/notices/unread").length, 0);
          assert.deepEqual(exchanges, [{ authCode: "fixture-code", loginType: scenario.mobile ? "workbench" : "scan" }]);
          assert.deepEqual(documents, [`${origin}${scenario.path}`, `${origin}/`], "login must reach the portal without a reload loop");
          assert.deepEqual(pageErrors, []);
        } finally {
          await context.close();
        }
      });
    }
    await t.test("backend settings never mount or poll the notification reminder", async () => {
      const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
      try {
        await context.addInitScript((session) => sessionStorage.setItem("mj_program_login_session", JSON.stringify(session)), staleSession);
        const noticeRequests = [];
        await context.route("**/api/**", (route) => {
          const path = new URL(route.request().url()).pathname;
          if (path === "/api/org/notices/unread") noticeRequests.push(path);
          return route.fulfill({ contentType: "application/json", body: JSON.stringify(path === "/api/auth/session/validate" ? staleSession : { items: [], total: 0, rules: [], revision: 1, orgRevision: 1 }) });
        });
        const page = await context.newPage();
        await page.clock.install();
        for (const path of ["/auth/settings/organization", "/auth/settings/notifications"]) {
          await page.goto(`${origin}${path}`);
          await page.getByText("后台管理", { exact: true }).first().waitFor();
          await page.clock.fastForward(46_000);
          await page.evaluate(() => {
            window.dispatchEvent(new Event("focus"));
            window.dispatchEvent(new Event("pageshow"));
            document.dispatchEvent(new Event("visibilitychange"));
          });
          assert.deepEqual(noticeRequests, []);
          assert.equal(await page.locator(".platform-notification-overlay").count(), 0);
        }
      } finally {
        await context.close();
      }
    });
  } finally {
    await browser.close();
    await server?.close();
  }
});
