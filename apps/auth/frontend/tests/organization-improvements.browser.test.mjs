import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { mkdir } from 'node:fs/promises';
import test from 'node:test';
const frontend = createRequire(new URL('../package.json', import.meta.url));
const { chromium } = createRequire(new URL('../../../../.codex-artifacts/package.json', import.meta.url))('playwright');
const { createServer } = await import(frontend.resolve('vite'));
const session = { sessionId: 'org-test', userId: 'admin', name: '测试管理员', canManagePlatformSettings: true, canConfigurePermissions: true, canManageEmployeeAccountStatus: true, canSyncContacts: true, canAccessInactiveEmployees: true, canStartProxy: true };
const departmentTree = [{ deptId: 1, parentDeptId: null, name: '测试公司', pinyin: 'ceshigongsi', children: [{ deptId: 2, parentDeptId: 1, name: '研发部', pinyin: 'yanfabu', pinyinInitials: 'yfb', children: [{ deptId: 3, parentDeptId: 2, name: '软件组', pinyin: 'ruanjianzu', children: [] }] }] }];
const members = [
  { userId: '001234567890123456789', name: '测试甲', accountStatus: '启用', departments: [{ deptId: 3, name: '软件组' }] },
  { userId: 'member-b', name: '测试乙', accountStatus: '禁用', departments: [{ deptId: 2, name: '研发部' }] },
  { userId: 'member-c', name: '测试丙', accountStatus: '启用', departments: [{ deptId: 2, name: '研发部' }] },
];

test('organization header, department search, confirmations, retries, sync and records work together', async () => {
  const server = await createServer({ root: fileURLToPath(new URL('../', import.meta.url)), server: { host: '127.0.0.1', port: 0, strictPort: false } });
  await server.listen();
  const browser = await chromium.launch({ headless: true });
  const artifacts = fileURLToPath(new URL('../../../../.codex-artifacts/organization-improvements/', import.meta.url));
  await mkdir(artifacts, { recursive: true });
  try {
    for (const width of [1440, 1024, 800]) {
      const context = await browser.newContext({ viewport: { width, height: 960 } });
      await context.addInitScript(value => sessionStorage.setItem('mj_program_login_session', JSON.stringify(value)), session);
      let failMembers = false, failTree = false, failPreview = false, stalePreview = false, syncPosts = 0;
      let enabledIds = [2, 3];
      const accountWrites = [], queries = [], errors = [];
      await context.route('**/api/**', async route => {
        const req = route.request(), url = new URL(req.url()), path = url.pathname;
        const reply = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
        if (path === '/api/auth/session/validate') return reply(session);
        if (path === '/api/org/departments/tree') return failTree ? reply({ error: '测试部门加载失败' }, 503) : reply({ items: departmentTree, orgRevision: 9 });
        if (path === '/api/org/enabled-departments') {
          if (req.method() === 'PUT') enabledIds = req.postDataJSON().departmentIds.map(Number);
          return reply({ departmentIds: enabledIds, revision: 1, orgRevision: 9 });
        }
        if (/^\/api\/org\/departments\/\d+$/.test(path)) return reply({ managers: [members[0], members[2]], manager: members[0], directEmployeeCount: 2, subtreeEmployeeCount: 3, orgRevision: 9 });
        if (path.endsWith('/employees') || path === '/api/org/employees') {
          queries.push({ path, q: url.searchParams.get('keyword'), children: url.searchParams.get('includeSubDepartments') });
          if (failMembers) return reply({ error: '测试人员加载失败' }, 503);
          const q = url.searchParams.get('keyword') || '';
          const items = q === '测试乙' ? [members[1]] : q === '无匹配' ? [] : members;
          return reply({ items, orgRevision: 9 });
        }
        if (path === '/api/org/account-status/preview') return failPreview ? reply({ error: '测试预览失败' }, 503) : reply({ count: 2, confirmationToken: 'signed-test-preview', affectsCurrentAccount: !url.searchParams.get('userId') });
        if (path.includes('/account-status')) {
          accountWrites.push(req.postDataJSON());
          return stalePreview ? reply({ code: 'ACCOUNT_PREVIEW_CHANGED', error: '账号范围或状态已变化，请重新核对影响人数后确认' }, 409) : reply({ ok: true });
        }
        if (path === '/api/dingtalk/sync_contacts') { syncPosts++; return reply({ syncRun: { runId: 'sync-test', status: 'running' } }, 202); }
        if (path.startsWith('/api/dingtalk/sync_contacts/status')) return reply({ lastSyncedAt: '2026-10-12T02:00:00Z', syncRun: { runId: 'sync-test', status: 'succeeded', summary: { departmentCount: 3, employeeCount: 3, departmentAddedCount: 1, departmentRemovedCount: 0, employeeAddedCount: 2, employeeMissingCount: 0 } } });
        if (path === '/api/org/account-operations') return reply({ total: 1, items: [{ id: 1, actorName: '测试管理员', actorUserId: 'admin', effectiveUserId: 'admin', accountStatus: '禁用', scope: 'employee', count: 1, createdAt: '2026-10-12T02:00:00Z', changes: [{ userId: 'member-b', name: '测试乙', before: '启用', after: '禁用' }] }] });
        return reply({ items: [] });
      });
      const page = await context.newPage();
      page.on('pageerror', error => errors.push(error.message));
      const base = `http://127.0.0.1:${server.httpServer.address().port}/auth/settings/organization`;
      await page.goto(`${base}?dept=2&scope=all`);
      await page.getByRole('table', { name: '组织成员' }).waitFor();
      const tree = page.getByRole('region', { name: '部门设置' });
      assert.equal(await page.getByRole('button', { name: '账号操作记录', exact: true }).count(), 0, 'account records are inside the operations dialog');
      assert.equal(await page.getByText(/^上次同步：/).count(), 0, 'sync information no longer occupies the page header');
      assert.ok(await tree.getByText('上级部门未启用').isVisible());
      assert.ok(await page.getByText('本部门 2 人 · 含下级 3 人').isVisible());
      await page.getByText('主管 2 人', { exact: true }).click();
      assert.equal(await page.getByRole('img', { name: /：部门主管$/ }).count(), 2);
      assert.ok(await page.getByRole('navigation', { name: '部门路径' }).getByRole('button', { name: '查看测试公司部门' }).isVisible());
      assert.equal(await page.getByRole('cell', { name: '禁用', exact: true }).count(), 1);
      assert.equal(await page.getByLabel('成员搜索范围').count(), 0);
      assert.equal(await page.getByRole('cell', { name: '软件组', exact: true }).count(), 1);
      assert.equal(await page.getByRole('cell', { name: '测试公司 / 研发部 / 软件组', exact: true }).count(), 0);
      const search = page.getByRole('searchbox', { name: '搜索部门成员姓名、ID或拼音' });
      await search.fill('测试乙');
      await page.getByText('当前匹配 1 人', { exact: true }).waitFor();
      assert.ok(queries.some(item => item.path === '/api/org/departments/2/employees' && item.q === '测试乙'));
      assert.equal(queries.some(item => item.path === '/api/org/employees'), false);
      assert.equal(new URL(page.url()).searchParams.get('scope'), null);
      await page.reload();
      await page.getByRole('table', { name: '组织成员' }).waitFor();
      assert.equal(await search.inputValue(), '测试乙');
      await page.getByRole('checkbox', { name: '包含下级部门', exact: true }).uncheck();
      await page.getByRole('table', { name: '组织成员' }).waitFor();
      assert.ok(queries.some(item => item.path === '/api/org/departments/2/employees' && item.children === '0'));
      await page.getByRole('checkbox', { name: '包含下级部门', exact: true }).check();
      await search.fill('无匹配');
      await page.getByText('未找到匹配成员，请调整搜索条件').waitFor();
      failMembers = true;
      await search.fill('错误');
      await page.getByText('测试人员加载失败').waitFor();
      failMembers = false;
      await page.getByRole('button', { name: '重新加载', exact: true }).click();
      await page.getByRole('table', { name: '组织成员' }).waitFor();
      await search.fill('');
      await page.getByText('当前匹配 3 人', { exact: true }).waitFor();
      const memberBounds = await page.getByRole('region', { name: '研发部人员', exact: true }).boundingBox();
      const actionBounds = await page.getByRole('button', { name: '操作', exact: true }).boundingBox();
      assert.ok(memberBounds.x + memberBounds.width <= width, 'member panel stays inside the viewport');
      assert.ok(actionBounds.x + actionBounds.width <= width, 'toolbar actions remain visible');
      const title = page.getByRole('heading', { name: '研发部', exact: true });
      const titleBounds = await title.boundingBox();
      const pathBounds = await page.getByRole('navigation', { name: '部门路径' }).boundingBox();
      const searchBounds = await search.boundingBox();
      const includeBounds = await page.getByRole('checkbox', { name: '包含下级部门', exact: true }).boundingBox();
      assert.ok(Number.parseFloat(await title.evaluate(node => getComputedStyle(node).fontSize)) >= 18);
      assert.ok(titleBounds.y + titleBounds.height <= pathBounds.y, 'department title appears before the path');
      if (memberBounds.width > 480) {
        assert.ok(Math.abs(searchBounds.y + searchBounds.height / 2 - (pathBounds.y + pathBounds.height / 2)) < 3, 'path and search share the second row');
      } else {
        assert.ok(pathBounds.y + pathBounds.height <= searchBounds.y, 'narrow panels wrap controls below the readable path');
      }
      assert.ok(Math.abs(includeBounds.y + includeBounds.height / 2 - (actionBounds.y + actionBounds.height / 2)) < 3, 'include children and actions share the second row');
      assert.ok(Math.abs(actionBounds.x + actionBounds.width - (memberBounds.x + memberBounds.width - 13)) < 3, 'actions align to the right edge');

      if (width < 1100) {
        const tableRegion = page.getByRole('region', { name: '成员表格，可使用方向键横向浏览' });
        await tableRegion.focus();
        await page.keyboard.press('ArrowRight');
        assert.ok(await tableRegion.evaluate(node => node.scrollLeft) > 0);
        await tableRegion.evaluate(node => { node.scrollLeft = 0; });
      }
      await page.screenshot({ path: `${artifacts}overview-${width}.png` });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await page.getByRole('button', { name: '操作测试甲' }).click();
      await page.getByRole('dialog', { name: '员工操作' }).getByRole('button', { name: /停用/ }).click();
      const confirm = page.getByRole('alertdialog');
      await confirm.getByRole('button', { name: '确认禁用' }).waitFor();
      assert.equal(accountWrites.length, 0);
      await page.keyboard.press('Escape');
      assert.equal(await confirm.count(), 0);
      assert.equal(accountWrites.length, 0);
      await page.keyboard.press('Escape');
      await page.getByRole('button', { name: '操作', exact: true }).click();
      await page.getByRole('dialog', { name: '操作', exact: true }).getByRole('button', { name: /全部禁用/ }).click();
      await confirm.getByText(/本次将禁用 2 人/).waitFor();
      assert.ok(await confirm.getByText(/当前会话也会失效/).isVisible());
      await page.screenshot({ path: `${artifacts}confirmation-${width}.png` });
      stalePreview = true;
      await confirm.getByRole('button', { name: '确认禁用' }).click();
      await confirm.getByRole('alert').waitFor();
      assert.equal(await confirm.getByRole('button', { name: '确认禁用' }).isDisabled(), true);
      stalePreview = false; failPreview = true;
      await confirm.getByRole('button', { name: '重新核对影响人数' }).click();
      await confirm.getByText('测试预览失败').waitFor();
      failPreview = false;
      await confirm.getByRole('button', { name: '重新核对影响人数' }).click();
      await confirm.getByText(/本次将禁用 2 人/).waitFor();
      await confirm.getByRole('button', { name: '确认禁用' }).click();
      await page.getByText('已禁用 2 人，操作记录已保存').waitFor();
      assert.equal(accountWrites.at(-1).confirmationToken, 'signed-test-preview');
      await page.getByRole('button', { name: '操作', exact: true }).click();
      const operations = page.getByRole('dialog', { name: '操作', exact: true });
      await operations.getByRole('region', { name: '通讯录同步状态' }).getByText('正常', { exact: true }).waitFor();
      assert.equal(await operations.getByRole('button', { name: '同步通讯录', exact: true }).count(), 1, 'there is a single sync action');
      await page.screenshot({ path: `${artifacts}operations-${width}.png` });
      await page.getByRole('button', { name: '账号操作记录', exact: true }).click();
      const records = page.getByRole('dialog', { name: '账号操作记录' });
      await records.getByText('禁用 1 人 · 单个账号').waitFor();
      await records.getByText('受影响人员（1）').click();
      assert.ok(await records.getByText('member-b').isVisible());
      await page.keyboard.press('Tab');
      assert.ok(await records.evaluate(node => node.contains(document.activeElement)), 'keyboard focus stays in the records drawer');
      await page.keyboard.press('Escape');
      await operations.waitFor();
      await page.waitForFunction(() => document.activeElement?.getAttribute('aria-label') === '账号操作记录');
      await page.getByRole('button', { name: '查看变更数量' }).click();
      const syncDetail = page.getByRole('dialog', { name: '通讯录同步详情' });
      await syncDetail.getByText('新增部门', { exact: true }).waitFor();
      assert.ok(await syncDetail.getByText('新增/返职人员', { exact: true }).isVisible());
      await page.keyboard.press('Escape');
      await operations.waitFor();
      await operations.getByRole('button', { name: '关闭操作窗口' }).click();
      await tree.getByRole('button', { name: '启用范围' }).click();
      await tree.getByRole('checkbox', { name: '启用测试公司' }).check();
      await page.getByRole('button', { name: '操作', exact: true }).click();
      await page.getByRole('button', { name: '同步通讯录', exact: true }).click();
      await page.getByRole('alertdialog', { name: '是否放弃修改' }).waitFor();
      assert.equal(syncPosts, 0);
      await page.getByRole('button', { name: '继续编辑', exact: true }).click();
      assert.equal(await tree.getByRole('checkbox', { name: '停用测试公司' }).isChecked(), true);
      await page.getByRole('button', { name: '同步通讯录', exact: true }).click();
      await page.getByRole('button', { name: '确认放弃', exact: true }).click();
      await page.getByText(/同步完成：3 个部门/).waitFor();
      assert.equal(syncPosts, 1);
      assert.equal(await tree.getByRole('checkbox').count(), 0);
      failTree = true;
      await page.reload();
      await tree.getByText('测试部门加载失败').waitFor();
      failTree = false;
      await tree.getByRole('button', { name: '重新加载部门' }).click();
      await page.getByRole('table', { name: '组织成员' }).waitFor();
      assert.deepEqual(errors, []);
      await context.close();
    }
  } finally { await browser.close(); await server.close(); }
});
