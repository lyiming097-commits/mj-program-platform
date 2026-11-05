# Apps

Each top-level folder is an independent Docker application.

- `auth/`: authentication center. Owns login, token issuing, token introspection, DingTalk auth, organization, employees, the `FULL_ACCESS_USER_IDS` whitelist and `auth-postgres`.
- `portal/`: platform portal. Owns the landing workspace, future shared platform modules and `portal-postgres`.
- `crm/`: CRM subsystem. Owns CRM frontend, CRM backend and `crm-postgres`.
- `cable-mall/`: cable mall subsystem. Owns cable mall frontend, backend APIs and `cable-mall-postgres`.
- `product-archive/`: product archive subsystem. Owns product data, certificates and `product-archive-postgres`.
- `starter-app/`: deployed blank starter App used to refine the standard page style before promoting it into future scaffolds.

Default rule:

- Each app may change only its own PostgreSQL container.
- Cross-system data access should go through API calls.
- Business apps validate identity by calling `auth-backend` introspection, then enforce their own permissions locally.
- Every app must own an `app.manifest.yaml`. The manifest is the source of truth for containers, public routes, Portal metadata and Secret mounts.
- Adding an app must not edit root Compose, gateway, Portal or Auth source files. In team development, the platform maintainer assigns a unique App ID and Git baseline, but does not merge an unfinished empty scaffold into production `main`. The developer creates the scaffold on the task branch with `python3 scripts/new_app.py <app-id> --no-deploy --yes`, modifies only that App directory, and hands it off with `python3 scripts/package_app.py <app-id> --base <trusted-baseline>` (Windows: `py -3 scripts/package_app.py <app-id> --base <trusted-baseline>`).
- A developer deploying to their own computer must explicitly use `local.env.docker`; production maintainers use `server.env.docker` only on the target server. Do not share production environment files, Secrets or data with App developers.

See `docs/APP_COLLABORATION.md` for the complete team handoff flow and `docs/APP_MANIFEST.md` for the manifest contract.
