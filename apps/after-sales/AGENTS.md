# App Development Rules

These rules apply to `apps/after-sales/`.

- Keep routine implementation changes inside `apps/after-sales/`.
- Integrate with other Apps only through documented APIs. Do not import their internals or connect to their databases.
- Do not modify root `compose.yaml`, `docker/gateway/nginx.conf`, `apps/auth/`, or `apps/portal/` for this App.
- Declare this App's services, routes, networks, volumes, and Secret mounts in `app.manifest.yaml`.
- After changing Django models, run `makemigrations` and commit the generated migration files with the model changes.
- Package handoff with `python3 scripts/package_app.py after-sales --base TASK_BASE_TAG_OR_COMMIT` (Windows: `py -3 scripts/package_app.py after-sales --base TASK_BASE_TAG_OR_COMMIT`), replacing the placeholder with the exact tag or commit assigned by the platform owner; never send local Secret, database, upload, cache or build directories.
- Changes outside this App require an explicit platform-level reason and user approval.
