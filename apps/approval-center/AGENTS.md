# App Development Rules

These rules apply to `apps/approval-center/`.

- Keep routine implementation changes inside `apps/approval-center/`.
- Integrate with other Apps only through documented APIs. Do not import their internals or connect to their databases.
- Do not modify root `compose.yaml`, `docker/gateway/nginx.conf`, `apps/auth/`, or `apps/portal/` for this App.
- Declare this App's services, routes, networks, volumes, and Secret mounts in `app.manifest.yaml`.
- Record details must use the shared `PlatformDetailDrawer` and keep the drawer presentation as the default. Use a full-page detail only when the App explicitly documents that exception.
- Custom Vue backdrops must use `v-backdrop-dismiss` from `@platform-ui/backdrop-dismiss.js`. Dismiss only after the same pointer presses and releases on the backdrop; never close with bare `@click.self` or `pointerup`. Keep existing unsaved-change and busy-state guards.
- After changing Django models, run `makemigrations` and commit the generated migration files with the model changes.
- Package handoff with `python3 scripts/package_app.py approval-center --base TASK_BASE_TAG_OR_COMMIT` (Windows: `py -3 scripts/package_app.py approval-center --base TASK_BASE_TAG_OR_COMMIT`), replacing the placeholder with the exact tag or commit assigned by the platform owner; never send local Secret, database, upload, cache or build directories.
- Changes outside this App require an explicit platform-level reason and user approval.
