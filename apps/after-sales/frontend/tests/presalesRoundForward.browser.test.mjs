import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const frontend = createRequire(new URL("../package.json", import.meta.url));
const browserTools = createRequire(new URL("../../../../.codex-artifacts/package.json", import.meta.url));
const { chromium } = browserTools(process.env.PLAYWRIGHT_MODULE || "playwright");
const { createServer } = await import(frontend.resolve("vite"));
const root = fileURLToPath(new URL("../", import.meta.url));

test("forwarded round opens in the project and can add a reasoned round or pass without resetting the page", { timeout: 90000 }, async () => {
  const server = await createServer({ root, configFile: path.join(root, "vite.config.ts"),
    cacheDir: path.resolve(root, "../../../.codex-artifacts/vite-after-sales-round-forward"),
    define: { "import.meta.env.VITE_DING_CORP_ID": JSON.stringify("mock-corp") }, server: { host: "127.0.0.1", port: 0 } });
  let browser;
  const project = {
    id: 301, code: "PS301", serviceType: "presales", source: "local", name: "轮次转发验证项目",
    customer: "验证学校", ownerName: "当前管理员", ownerUserId: "service-admin", status: "in_progress",
    currentNodeKey: "budget-match", businessData: {}, assignments: [], events: [],
    permissions: { canManage: true, canDelete: true, canSettle: true },
    nodes: [
      { id: 3011, nodeKey: "early-approval", name: "前期立项", kind: "approval", status: "completed", enabled: true, sequence: 1, businessData: { outcome: "approved" } },
      { id: 3012, nodeKey: "early-plan", name: "前期方案", kind: "delivery", status: "active", enabled: true, sequence: 2,
        updatedAt: "2026-10-14T10:00:00+00:00", businessData: { schemeRounds: [
          { roundId: "round-one", note: "第一轮原备注", attachmentIds: ["880"] },
          { roundId: "round-two", note: "第二轮原备注", attachmentIds: ["881", "882"] },
        ] } },
      { id: 3013, nodeKey: "budget-match", name: "预算匹配", kind: "delivery", status: "active", enabled: true, sequence: 3, businessData: {} },
    ],
  };
  for (const item of project.nodes) item.permissions = { canEdit: item.status === "active", canAssign: true };
  const node = project.nodes[1];
  const attachments = [
    { id: 880, originalName: "第一轮专属方案.pdf" },
    { id: 881, originalName: "待调整方案.pdf" },
    { id: 882, originalName: "沿用的方案.pdf" },
  ].map(item => ({ ...item, category: "scheme_submission", mimeType: "application/pdf", size: 512, canDelete: false }));
  const requests = [];
  const errors = [];
  let sequence = 0;
  let processFailure = false;
  let holdProcess = null;
  let saveFailure = false;
  const stamp = () => { node.updatedAt = `2026-10-14T10:00:${String(++sequence).padStart(2, "0")}.123456+00:00`; };
  try {
    await server.listen();
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || undefined });
    const pdfPage = await browser.newPage();
    await pdfPage.setContent('<style>.page { height: 250mm; break-after: page; font-size: 40px; }</style><div class="page">Round reason page one</div><div>Round reason page two</div>');
    const reasonPdf = { name: "待提交说明.pdf", mimeType: "application/octet-stream", buffer: await pdfPage.pdf({ format: "A4", printBackground: true }) };
    await pdfPage.close();
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.on("pageerror", error => errors.push(error.message));
    page.on("dialog", dialog => dialog.type() === "beforeunload" ? dialog.accept() : dialog.dismiss());
    await page.addInitScript(() => {
      sessionStorage.setItem("mj_program_login_session", JSON.stringify({ sessionId: "round-forward-test", userId: "service-admin", name: "当前管理员", loginType: "scan" }));
      window.__shareCards = [];
      window.dd = { env: { platform: "pc" }, config: () => {}, error: () => {}, ready: callback => callback(),
        biz: { util: { share: payload => { window.__shareCards.push(payload); payload.onSuccess({}); } } } };
    });
    await page.route("https://g.alicdn.com/**", route => route.fulfill({ contentType: "text/javascript", body: "" }));
    await page.route("**/api/**", async route => {
      const url = new URL(route.request().url());
      const method = route.request().method();
      let status = 200;
      let body = { items: [] };
      if (url.pathname === "/api/auth/session/validate") {
        body = { sessionId: "round-forward-test", userId: "service-admin", name: "当前管理员", loginType: "scan" };
      } else if (url.pathname === "/api/after-sales/session/") {
        body = { canManageApp: true, canManageSettings: true, appPermission: "admin" };
      } else if (url.pathname === "/api/auth/dingtalk/jsapi_config") {
        assert.equal(url.searchParams.get("jsApiList"), "biz.util.share");
        body = { corpId: "corp", agentId: "agent", signature: "mock-signature", nonceStr: "nonce", timeStamp: 123 };
      } else if (url.pathname === "/api/after-sales/projects") {
        body = { items: [project], total: 1, page: 1, pageSize: 20, totalPages: 1 };
      } else if (url.pathname === "/api/after-sales/projects/301") {
        body = { item: project };
      } else if (url.pathname === "/api/after-sales/attachments") {
        if (method === "POST") {
          const contentType = route.request().headers()["content-type"];
          const form = await new Request("http://test.local/", { method: "POST", headers: { "content-type": contentType }, body: route.request().postDataBuffer() }).formData();
          assert.equal(form.get("roundIndex"), "2");
          assert.equal(form.get("roundId"), "round-three");
          const file = form.get("file");
          const item = { id: 992 + attachments.filter(row => row.id >= 992).length, originalName: file.name,
            category: form.get("category"), mimeType: file.type, size: file.size, canDelete: true, createdAt: new Date().toISOString() };
          attachments.push(item);
          status = 201;
          body = { ok: true, item };
        } else body = { items: attachments };
      } else if (url.pathname === "/api/after-sales/attachments/990/download") {
        await route.fulfill({ contentType: "image/png", body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=", "base64") });
        return;
      } else if (url.pathname === "/api/after-sales/attachments/991/download") {
        await route.fulfill({ contentType: "application/octet-stream", body: "cad changes" });
        return;
      } else if (url.pathname === "/api/after-sales/projects/301/nodes/early-plan") {
        assert.equal(method, "PATCH");
        const payload = route.request().postDataJSON();
        requests.push({ path: url.pathname, payload });
        if (saveFailure) { status = 503; body = { error: "保存失败", code: "SAVE_FAILED" }; }
        else if (payload.expectedUpdatedAt !== node.updatedAt) { status = 409; body = { error: "本轮内容已变动，请刷新项目后重新处理", code: "PRESALES_ROUND_CONFLICT" }; }
        else { node.businessData = { ...node.businessData, ...payload.businessData }; stamp(); body = { item: project }; }
      } else if (url.pathname === "/api/after-sales/projects/301/advance"
        || url.pathname === "/api/after-sales/projects/301/nodes/early-plan/version") {
        const payload = route.request().postDataJSON();
        requests.push({ path: url.pathname, payload });
        if (payload.expectedUpdatedAt !== node.updatedAt) {
          status = 409;
          body = { error: "本轮内容已被其他人更新，请刷新项目后再保存或处理", code: "PRESALES_ROUND_CONFLICT" };
        } else {
          node.businessData = { ...node.businessData, ...payload.businessData };
          if (url.pathname.endsWith("/advance")) node.status = "completed";
          stamp();
          body = { item: project };
        }
      } else if (url.pathname.endsWith("/rounds/prepare-forward")) {
        const payload = route.request().postDataJSON();
        requests.push({ path: url.pathname, payload });
        if (payload.expectedUpdatedAt !== node.updatedAt) {
          status = 409; body = { error: "本轮内容已变动，请刷新项目后重新处理", code: "PRESALES_ROUND_CONFLICT" };
        } else {
          assert.ok(!payload.roundId || payload.roundId === node.businessData.schemeRounds[payload.roundIndex].roundId);
          node.businessData.schemeRounds.forEach((round, index) => { round.roundId ||= `saved-blank-round-${index}`; });
          body = { item: project, roundId: node.businessData.schemeRounds[payload.roundIndex].roundId };
        }
      } else if (url.pathname.endsWith("/rounds/process")) {
        const contentType = route.request().headers()["content-type"] || "";
        let payload;
        let files = [];
        if (contentType.startsWith("multipart/form-data")) {
          const form = await new Request("http://test.local/", { method: "POST", headers: { "content-type": contentType }, body: route.request().postDataBuffer() }).formData();
          payload = JSON.parse(form.get("payload"));
          files = form.getAll("reasonFiles");
        } else payload = route.request().postDataJSON();
        requests.push({ path: url.pathname, payload });
        assert.equal(payload.expectedUpdatedAt, node.updatedAt);
        assert.equal(payload.roundId, node.businessData.schemeRounds.at(-1).roundId);
        if (holdProcess) await holdProcess;
        if (processFailure) { status = 409; body = { error: "本轮内容已变动，请刷新项目后重新处理", code: "PRESALES_ROUND_CONFLICT" }; }
        else {
          if (payload.action === "add_round") {
            assert.ok(payload.reason.trim());
            assert.deepEqual(files.map(file => file.name), ["客户批注.png", "修改明细.dwg"]);
            assert.equal(await files[1].text(), "cad changes");
            const reasonAttachmentIds = files.map((file, index) => {
              const id = 990 + index;
              attachments.push({ id, originalName: file.name, category: "scheme_submission", mimeType: file.type, size: file.size, canDelete: false,
                downloadUrl: `/api/after-sales/attachments/${id}/download` });
              return String(id);
            });
            node.businessData.schemeRounds.push({ roundId: "round-three", reason: payload.reason, note: "", attachmentIds: [], reasonAttachmentIds });
          } else if (payload.action === "remove_attachment") {
            const latest = node.businessData.schemeRounds.at(-1);
            latest.attachmentIds = latest.attachmentIds.filter(id => String(id) !== String(payload.attachmentId));
          } else { node.status = "completed"; node.permissions.canEdit = false; }
          stamp();
          project.events.push({ id: sequence, title: payload.action === "pass" ? "第3轮通过" : "新增第3轮", detail: payload.reason || "", eventType: "presales_round_processed" });
          body = { item: project };
        }
      }
      await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    });
    const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
    const target = `${origin}/after-sales/presales/?projectId=301&nodeKey=early-plan&roundId=round-two`;
    await page.goto(target);
    const dialog = number => page.getByRole("dialog", { name: `第 ${number} 次提交`, exact: true });
    try { await dialog(2).waitFor({ timeout: 10000 }); }
    catch (reason) {
      throw new Error(JSON.stringify({ body: await page.locator('body').innerText(), errors, requests }), { cause: reason });
    }
    assert.equal(await dialog(2).getByLabel("备注", { exact: true }).inputValue(), "第二轮原备注");
    assert.equal(await dialog(2).getByRole("button", { name: "通过", exact: true }).count(), 1);
    await dialog(2).getByRole("button", { name: "保存并关闭", exact: true }).click();
    assert.equal(await page.getByRole("tab", { name: /节点详情/ }).getAttribute("aria-selected"), "true");
    await page.getByRole("button", { name: "第 1 次提交：查看附件和备注", exact: true }).click();
    assert.equal(await dialog(1).getByLabel("备注", { exact: true }).getAttribute("readonly"), "");
    assert.equal(await dialog(1).locator('input[type="file"]').count(), 0);
    assert.equal(await dialog(1).getByRole("button", { name: "保存并关闭", exact: true }).count(), 0);
    assert.equal(await dialog(1).getByRole("button", { name: "通过", exact: true }).count(), 0);
    assert.equal(await dialog(1).getByRole("button", { name: /^移除：/ }).count(), 0);
    await dialog(1).getByRole("button", { name: "关闭", exact: true }).last().click();
    await page.getByRole("button", { name: "转发第 2 轮", exact: true }).click();
    await page.waitForFunction(() => window.__shareCards.length === 1);
    const card = await page.evaluate(() => window.__shareCards[0]);
    assert.match(card.title, /轮次转发验证项目.*前期方案.*第2轮/);
    assert.equal(new URL(new URL(card.url).searchParams.get("url")).searchParams.get("roundId"), "round-two");

    // A remote edit between opening and forwarding must not be approved unseen.
    stamp();
    await page.getByRole("button", { name: "转发第 2 轮", exact: true }).click();
    await page.getByRole("alert").filter({ hasText: "本轮内容已变动，请刷新项目后重新处理" }).first().waitFor();
    assert.equal(await page.evaluate(() => window.__shareCards.length), 1);
    await page.reload();
    await dialog(2).waitFor();
    await dialog(2).getByRole("button", { name: "保存并关闭", exact: true }).click();

    // Browser copying must also produce an AppLink that opens inside DingTalk.
    await page.evaluate(() => { delete window.dd; });
    await page.getByRole("button", { name: "转发第 2 轮", exact: true }).click();
    const linkDialog = page.getByRole("dialog", { name: "转发项目轮次", exact: true });
    await linkDialog.waitFor();
    const copiedLink = await linkDialog.getByLabel("项目轮次链接").inputValue();
    const copiedAppLink = new URL(copiedLink);
    assert.equal(copiedAppLink.origin, "https://applink.dingtalk.com");
    assert.equal(copiedAppLink.pathname, "/page/link");
    assert.equal(copiedAppLink.searchParams.get("targetDesktop"), "workbench");
    assert.equal(copiedAppLink.searchParams.get("url"), target);
    await page.evaluate(() => {
      Object.defineProperty(navigator.clipboard, "writeText", { configurable: true,
        value: async value => { window.__copiedRoundLink = value; } });
    });
    await linkDialog.getByRole("button", { name: "复制链接", exact: true }).click();
    assert.equal(await page.evaluate(() => window.__copiedRoundLink), copiedLink);
    await linkDialog.getByRole("button", { name: "关闭", exact: true }).last().click();

    saveFailure = true;
    const preparedBeforeFailure = requests.filter(item => item.path.endsWith("/rounds/prepare-forward")).length;
    await page.getByRole("button", { name: "第 2 次提交：填写附件和备注", exact: true }).click();
    await dialog(2).getByLabel("备注", { exact: true }).fill("网络失败期间填写的备注");
    await dialog(2).getByRole("button", { name: "保存并关闭", exact: true }).click();
    await page.getByRole("alert").filter({ hasText: "保存失败" }).first().waitFor();
    await page.getByRole("button", { name: "转发第 2 轮", exact: true }).click();
    await page.getByRole("button", { name: "转发第 2 轮", exact: true }).waitFor();
    assert.equal(await linkDialog.count(), 0);
    assert.equal(requests.filter(item => item.path.endsWith("/rounds/prepare-forward")).length, preparedBeforeFailure);
    saveFailure = false;

    await page.getByRole("button", { name: "第 2 次提交：填写附件和备注", exact: true }).click();
    await dialog(2).getByLabel("备注", { exact: true }).fill("处理前补充的备注");
    await dialog(2).getByRole("button", { name: "新增一轮", exact: true }).click();
    const reason = page.getByRole("dialog", { name: "新增一轮", exact: true });
    assert.equal(await reason.getByText("必填", { exact: true }).count(), 0);
    await reason.getByRole("button", { name: "确认新增", exact: true }).click();
    await reason.getByRole("alert").getByText("请填写新增一轮的原因", { exact: true }).waitFor();
    assert.equal(requests.filter(item => item.path.endsWith("/rounds/process")).length, 0);
    await reason.getByLabel(/新增原因/).fill("补充设备数量并调整布局");
    const reasonFiles = [
      { name: "客户批注.png", mimeType: "image/png", buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=", "base64") },
      { name: "修改明细.dwg", mimeType: "application/octet-stream", buffer: Buffer.from("cad changes") },
    ];
    await reason.getByLabel("添加原因附件", { exact: true }).setInputFiles(reasonFiles);
    await reason.getByText("客户批注.png", { exact: true }).waitFor();
    await reason.getByText("修改明细.dwg", { exact: true }).waitFor();
    assert.equal(await reason.getByLabel("添加原因附件", { exact: true }).getAttribute("accept"), null);

    // Pending files preview locally, before a round/file has been submitted.
    await reason.getByRole("button", { name: "预览缩略图：客户批注.png", exact: true }).click();
    const pendingImage = page.getByRole("dialog", { name: "客户批注.png", exact: true });
    await pendingImage.waitFor();
    await pendingImage.getByRole("img", { name: "客户批注.png", exact: true }).waitFor();
    await page.keyboard.press("Escape");
    await pendingImage.waitFor({ state: "hidden" });
    await reason.waitFor();
    assert.equal(await reason.getByRole("button", { name: "预览缩略图：客户批注.png", exact: true }).evaluate(element => element === document.activeElement), true);
    assert.equal(await page.getByRole("alertdialog", { name: "是否放弃修改", exact: true }).count(), 0);
    assert.equal(await reason.getByLabel(/新增原因/).inputValue(), "补充设备数量并调整布局");

    await reason.getByLabel("添加原因附件", { exact: true }).setInputFiles(reasonPdf);
    await reason.getByRole("button", { name: `预览文件：${reasonPdf.name}`, exact: true }).click();
    const pendingPdf = page.getByRole("dialog", { name: reasonPdf.name, exact: true });
    await pendingPdf.getByRole("img", { name: `${reasonPdf.name} 第 1 页`, exact: true }).waitFor();
    await pendingPdf.getByText("1 / 2", { exact: true }).waitFor();
    await page.waitForFunction(() => {
      const canvas = document.querySelector('.as-image-preview-dialog--pdf canvas');
      if (!canvas?.width || !canvas?.height) return false;
      const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
      let nonWhite = 0;
      for (let i = 0; i < pixels.length; i += 4) if (pixels[i + 3] && pixels[i] < 220) nonWhite++;
      return nonWhite > 100;
    });
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      const bounds = await pendingPdf.boundingBox();
      assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width + 1);
      assert.deepEqual(await pendingPdf.evaluate(element => ({
        horizontal: element.scrollWidth > element.clientWidth + 1,
        vertical: element.scrollHeight > element.clientHeight + 1,
      })), { horizontal: false, vertical: false });
    }
    await page.setViewportSize({ width: 1440, height: 900 });
    await pendingPdf.getByRole("button", { name: "下一页", exact: true }).click();
    await pendingPdf.getByRole("img", { name: `${reasonPdf.name} 第 2 页`, exact: true }).waitFor();
    await page.keyboard.press("Tab");
    assert.equal(await pendingPdf.evaluate(element => element.contains(document.activeElement)), true);
    const pendingDownload = page.waitForEvent("download");
    await pendingPdf.getByRole("button", { name: "下载原件", exact: true }).click();
    assert.equal((await pendingDownload).suggestedFilename(), reasonPdf.name);
    await page.screenshot({ path: path.resolve(root, "../../../.codex-artifacts/after-sales-pending-reason-pdf-preview.png") });
    await page.keyboard.press("Escape");
    await pendingPdf.waitFor({ state: "hidden" });
    await reason.waitFor();
    assert.equal(await reason.getByRole("button", { name: `预览文件：${reasonPdf.name}`, exact: true }).evaluate(element => element === document.activeElement), true);
    assert.equal(await reason.getByLabel(/新增原因/).inputValue(), "补充设备数量并调整布局");
    assert.equal(requests.filter(item => item.path.endsWith("/rounds/process")).length, 0);
    assert.equal(attachments.length, 3);
    await reason.getByRole("button", { name: `移除 ${reasonPdf.name}`, exact: true }).click();
    assert.equal(await reason.getByRole("button", { name: `预览文件：${reasonPdf.name}`, exact: true }).count(), 0);
    await reason.getByRole("button", { name: "预览：客户批注.png", exact: true }).click();
    await pendingImage.getByRole("button", { name: "关闭大图", exact: true }).click();
    await reason.waitFor();
    for (const width of [1024, 390, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      const bounds = await reason.boundingBox();
      assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width + 1);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    }
    await page.screenshot({ path: path.resolve(root, "../../../.codex-artifacts/after-sales-round-reason-attachments.png") });
    await reason.getByRole("button", { name: "取消", exact: true }).click();
    const discard = page.getByRole("alertdialog", { name: "是否放弃修改", exact: true });
    await discard.waitFor();
    await discard.getByRole("button", { name: "继续编辑", exact: true }).click();
    assert.equal(await reason.getByLabel(/新增原因/).inputValue(), "补充设备数量并调整布局");
    await reason.getByText("客户批注.png", { exact: true }).waitFor();

    // Root navigation must protect the pending reason/files too.
    const beforeNavigation = page.url();
    await page.getByRole("button", { name: "服务团队", exact: true }).click({ force: true });
    await discard.waitFor();
    await discard.getByRole("button", { name: "继续编辑", exact: true }).click();
    assert.equal(page.url(), beforeNavigation);
    await reason.getByText("修改明细.dwg", { exact: true }).waitFor();

    // Discarding is local only; the outer entry opens a clean reason draft.
    await reason.getByRole("button", { name: "取消", exact: true }).click();
    await discard.getByRole("button", { name: "确认放弃", exact: true }).click();
    await reason.waitFor({ state: "hidden" });
    assert.equal(attachments.length, 3);
    assert.equal(requests.filter(item => item.path.endsWith("/rounds/process")).length, 0);
    await dialog(2).getByRole("button", { name: "保存并关闭", exact: true }).click();
    await page.getByRole("button", { name: "新增一轮", exact: true }).click();
    await reason.waitFor();
    assert.equal(await reason.getByLabel(/新增原因/).inputValue(), "");
    assert.equal(await reason.getByText("暂无附件", { exact: true }).count(), 1);
    await reason.getByLabel(/新增原因/).fill("补充设备数量并调整布局");
    await reason.getByLabel("添加原因附件", { exact: true }).setInputFiles(reasonFiles);

    processFailure = true;
    await reason.getByRole("button", { name: "确认新增", exact: true }).click();
    await reason.getByRole("alert").filter({ hasText: "本轮内容已变动" }).waitFor();
    assert.equal(await reason.getByLabel(/新增原因/).inputValue(), "补充设备数量并调整布局");
    await reason.getByText("修改明细.dwg", { exact: true }).waitFor();
    assert.equal(node.businessData.schemeRounds.length, 2);
    assert.equal(attachments.length, 3);
    processFailure = false;
    let releaseProcess;
    holdProcess = new Promise(resolve => { releaseProcess = resolve; });
    await reason.getByRole("button", { name: "确认新增", exact: true }).click();
    await reason.getByText("正在保存原因和附件，请稍候…", { exact: true }).waitFor();
    assert.equal(await reason.getByRole("button", { name: "正在保存…", exact: true }).isDisabled(), true);
    assert.equal(await reason.getByRole("button", { name: "取消", exact: true }).isDisabled(), true);
    assert.equal(await reason.getByLabel("添加原因附件", { exact: true }).isDisabled(), true);
    assert.equal(await reason.getByRole("button", { name: "关闭", exact: true }).isDisabled(), true);
    await page.keyboard.press("Escape");
    assert.equal(await reason.count(), 1);
    releaseProcess();
    holdProcess = null;
    await dialog(3).waitFor();
    const reasonAttachments = dialog(3).getByRole("region", { name: "新增原因附件", exact: true });
    await reasonAttachments.getByText("客户批注.png", { exact: true }).waitFor();
    await reasonAttachments.getByText("修改明细.dwg", { exact: true }).waitFor();
    await page.waitForFunction(() => [...document.querySelectorAll('section[aria-label="新增原因附件"] img')].some(img => img.complete && img.naturalWidth > 0));
    await reasonAttachments.getByRole("button", { name: "预览：客户批注.png", exact: true }).first().click();
    const imagePreview = page.getByRole("dialog", { name: "客户批注.png", exact: true });
    await imagePreview.waitFor();
    await imagePreview.getByRole("button", { name: "关闭大图", exact: true }).click();
    const downloadPromise = page.waitForEvent("download");
    await reasonAttachments.getByRole("button", { name: "下载：修改明细.dwg", exact: true }).first().click();
    assert.equal((await downloadPromise).suggestedFilename(), "修改明细.dwg");
    assert.equal(await reasonAttachments.getByRole("button", { name: /移除|删除/ }).count(), 0);
    assert.equal(await reasonAttachments.locator('input[type="file"]').count(), 0);
    assert.deepEqual(node.businessData.schemeRounds[2].reasonAttachmentIds, ["990", "991"]);
    assert.deepEqual(node.businessData.schemeRounds[2].attachmentIds, []);
    assert.deepEqual(node.businessData.schemeRounds[1].attachmentIds, ["881", "882"]);
    assert.equal(await dialog(3).getByText("待调整方案.pdf", { exact: true }).count(), 0);
    assert.equal(await dialog(3).getByText("沿用的方案.pdf", { exact: true }).count(), 0);
    const uploadedSave = page.waitForResponse(response => {
      const request = response.request();
      return request.method() === "PATCH" && new URL(request.url()).pathname.endsWith("/nodes/early-plan")
        && request.postDataJSON().businessData?.schemeRounds?.at(-1).attachmentIds?.length === 2;
    });
    await dialog(3).getByLabel("上传附件", { exact: true }).setInputFiles([
      { name: "待调整方案.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 new revision") },
      { name: "沿用的方案.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 another revision") },
    ]);
    await uploadedSave;
    await dialog(3).getByText("待调整方案.pdf", { exact: true }).waitFor();
    await dialog(3).getByText("沿用的方案.pdf", { exact: true }).waitFor();
    assert.equal(await dialog(3).getByText("第一轮专属方案.pdf", { exact: true }).count(), 0);
    assert.deepEqual(node.businessData.schemeRounds[2].attachmentIds, ["992", "993"]);
    await dialog(3).getByRole("button", { name: "移除：待调整方案.pdf", exact: true }).click();
    const removal = page.getByRole("alertdialog", { name: "移除本轮附件", exact: true });
    await removal.waitFor();
    await page.screenshot({ path: path.resolve(root, "../../../.codex-artifacts/after-sales-round-attachment-removal.png") });
    await page.keyboard.press("Escape");
    await removal.waitFor({ state: "hidden" });
    assert.deepEqual(node.businessData.schemeRounds[2].attachmentIds, ["992", "993"]);
    assert.equal(await dialog(3).getByRole("button", { name: "移除：待调整方案.pdf" }).evaluate(el => el === document.activeElement), true);
    await dialog(3).getByLabel("备注", { exact: true }).fill("保留另一份方案");
    await dialog(3).getByRole("button", { name: "移除：待调整方案.pdf", exact: true }).click();
    processFailure = true;
    await removal.getByRole("button", { name: "确认移除", exact: true }).click();
    await removal.getByRole("alert").waitFor();
    assert.deepEqual(node.businessData.schemeRounds[2].attachmentIds, ["992", "993"]);
    processFailure = false;
    await removal.getByRole("button", { name: "确认移除", exact: true }).click();
    await removal.waitFor({ state: "hidden" });
    await dialog(3).getByText("待调整方案.pdf", { exact: true }).waitFor({ state: "hidden" });
    await dialog(3).getByText("沿用的方案.pdf", { exact: true }).waitFor();
    assert.equal(await dialog(3).getByRole("button", { name: "保存并关闭", exact: true }).evaluate(el => el === document.activeElement), true);
    assert.deepEqual(node.businessData.schemeRounds[2].attachmentIds, ["993"]);
    assert.deepEqual(node.businessData.schemeRounds[1].attachmentIds, ["881", "882"]);
    assert.equal(await dialog(3).getByLabel("备注", { exact: true }).inputValue(), "保留另一份方案");
    assert.equal(node.businessData.schemeRounds[0].note, "第一轮原备注");
    assert.equal(node.businessData.schemeRounds[1].note, "处理前补充的备注");
    assert.equal(node.status, "active");
    await dialog(3).getByText("补充设备数量并调整布局", { exact: false }).waitFor();
    await page.screenshot({ path: path.resolve(root, "../../../.codex-artifacts/after-sales-round-process.png") });
    for (const width of [1440, 1024]) {
      await page.setViewportSize({ width, height: 900 });
      const bounds = await dialog(3).boundingBox();
      assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width + 1);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    }
    processFailure = true;
    await dialog(3).getByRole("button", { name: "通过", exact: true }).click();
    await dialog(3).getByRole("alert").waitFor();
    assert.equal(node.status, "active");
    processFailure = false;
    await dialog(3).getByRole("button", { name: "通过", exact: true }).click();
    await dialog(3).waitFor({ state: "hidden" });
    assert.equal(node.status, "completed");
    assert.equal(project.nodes[2].status, "active", "parallel node remains independent");
    assert.equal(await page.getByRole("button", { name: "新增一轮", exact: true }).count(), 0);
    await page.getByRole("button", { name: "第 3 次提交：查看附件和备注", exact: true }).click();
    assert.equal(await dialog(3).getByLabel("备注", { exact: true }).getAttribute("readonly"), "");
    assert.equal(await dialog(3).locator('input[type="file"]').count(), 0);
    assert.equal(await dialog(3).getByRole("button", { name: "通过", exact: true }).count(), 0);
    await dialog(3).getByRole("button", { name: "关闭", exact: true }).last().click();
    assert.equal(await page.getByRole("tab", { name: /节点详情/ }).getAttribute("aria-selected"), "true");
    assert.equal(new URL(page.url()).searchParams.get("projectId"), "301");
    assert.ok(await page.getByText("轮次转发验证项目", { exact: true }).count());

    await page.reload();
    await dialog(2).waitFor();
    assert.equal(await dialog(2).getByRole("button", { name: "通过", exact: true }).count(), 0);
    await dialog(2).getByText("节点已通过，本轮资料供查看。", { exact: true }).waitFor();
    await dialog(2).getByRole("button", { name: "关闭", exact: true }).last().click();
    await page.getByRole("button", { name: "第 3 次提交：查看附件和备注", exact: true }).click();
    await dialog(3).getByRole("region", { name: "新增原因附件" }).getByText("修改明细.dwg", { exact: true }).waitFor();
    await dialog(3).getByRole("button", { name: "关闭", exact: true }).last().click();
    await page.goto(`${origin}/after-sales/presales/?projectId=301&nodeKey=early-plan&roundId=removed-round`);
    await page.getByText("转发的轮次已删除，请查看项目中的最新轮次", { exact: true }).waitFor();
    assert.equal(await dialog(2).count(), 0);
    const fresh = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    let loggedIn = false;
    await fresh.addInitScript(() => {
      window.dd = { env: { platform: "pc" }, runtime: { permission: { requestAuthCode: ({ onSuccess }) => onSuccess({ code: "mock-native-auth" }) } } };
    });
    await fresh.route("https://g.alicdn.com/**", route => route.fulfill({ contentType: "text/javascript", body: "" }));
    await fresh.route("**/api/**", async route => {
      const url = new URL(route.request().url());
      let status = 200;
      let body = { items: [] };
      if (url.pathname === "/api/auth/session/validate") {
        status = loggedIn ? 200 : 401;
        body = loggedIn ? { sessionId: "fresh-round-session", userId: "recipient" } : { error: "Missing auth token", code: "MISSING_AUTH_TOKEN" };
      } else if (url.pathname === "/api/auth/code") {
        assert.deepEqual(route.request().postDataJSON(), { authCode: "mock-native-auth", loginType: "workbench" });
        loggedIn = true;
        body = { sessionId: "fresh-round-session", userId: "recipient" };
      } else if (url.pathname === "/api/after-sales/session/") {
        assert.ok(loggedIn);
        body = { canManageApp: true, canManageSettings: false, appPermission: "sales", appPermissions: ["sales"] };
      } else if (url.pathname === "/api/after-sales/projects/301") body = { item: project };
      else if (url.pathname === "/api/after-sales/projects") body = { items: [project], total: 1 };
      await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    });
    await fresh.goto(target);
    await fresh.getByRole("dialog", { name: "第 2 次提交", exact: true }).waitFor();
    assert.equal(new URL(fresh.url()).searchParams.get("roundId"), "round-two");
    await fresh.close();
    // The initial display row can be forwarded with optional material fields.
    node.status = "active";
    node.permissions.canEdit = true;
    node.businessData.schemeRounds = [];
    stamp();
    await page.goto(`${origin}/after-sales/presales/?projectId=301&nodeKey=early-plan`);
    await page.locator("summary").filter({ hasText: "前期方案推进" }).click();
    await page.getByRole("button", { name: "转发第 1 轮", exact: true }).click();
    await page.waitForFunction(() => window.__shareCards.length === 1);
    assert.equal(node.businessData.schemeRounds.length, 1);
    assert.equal(node.businessData.schemeRounds[0].roundId, "saved-blank-round-0");
    assert.equal(node.businessData.schemeRounds[0].note, "");

    // The footer action must carry the displayed version just like forwarding.
    const displayedVersion = node.updatedAt;
    node.businessData.schemeRounds[0].note = "其他人刚保存的备注";
    stamp();
    await page.getByRole("button", { name: "节点通过", exact: true }).click();
    await page.getByRole("alert").filter({ hasText: "本轮内容已被其他人更新" }).first().waitFor();
    assert.equal(requests.at(-1).payload.expectedUpdatedAt, displayedVersion);
    assert.equal(node.status, "active");
    assert.equal(node.businessData.schemeRounds[0].note, "其他人刚保存的备注");

    // The version-submission API uses the same explicit field mapping.
    async function submitVersion(expectedUpdatedAt) {
      return page.evaluate(async payload => {
        const { serviceApi } = await import("/after-sales/src/serviceApi.js");
        try {
          await serviceApi.projectAction(301, "submit_version", payload);
          return { ok: true };
        } catch (reason) {
          return { ok: false, code: reason.code, status: reason.status };
        }
      }, { node_key: "early-plan", expectedUpdatedAt, businessData: structuredClone(node.businessData) });
    }
    assert.deepEqual(await submitVersion(displayedVersion), { ok: false, code: "PRESALES_ROUND_CONFLICT", status: 409 });
    const version = node.updatedAt;
    assert.deepEqual(await submitVersion(version), { ok: true });
    assert.equal(requests.at(-1).payload.expectedUpdatedAt, version);
    assert.equal(node.status, "active");
    assert.equal(node.businessData.schemeRounds[0].note, "其他人刚保存的备注");

    await page.reload();
    await page.getByRole("button", { name: "节点通过", exact: true }).waitFor();
    const currentVersion = node.updatedAt;
    await page.getByRole("button", { name: "节点通过", exact: true }).click();
    await page.getByRole("status").filter({ hasText: "节点已通过" }).first().waitFor();
    assert.equal(requests.at(-1).payload.expectedUpdatedAt, currentVersion);
    assert.equal(node.status, "completed");
    assert.equal(project.nodes[2].status, "active");
    assert.equal(node.businessData.schemeRounds[0].note, "其他人刚保存的备注");
    assert.deepEqual(errors, []);
  } finally { await browser?.close(); await server.close(); }
});
