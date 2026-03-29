# add-vless-proxy-profiles

## Why

Operators need to route different ChatGPT accounts through different outbound proxy connections instead of relying on one process-wide proxy path.

The current implementation only supports environment-based outbound proxying. That is too coarse for multi-account deployments that need:

- several saved VLESS connections
- one service-level default connection
- per-account overrides with explicit `inherit default | direct | specific profile`

## What Changes

- add encrypted VLESS proxy profile storage with dashboard CRUD
- add service-level default connection setting
- add per-account connection assignment API and UI
- resolve effective outbound proxy dynamically for account-bound HTTP, websocket, usage-refresh, and token-refresh traffic
- add generated `xray-client` sidecar config and compose wiring

## Impact

- Code: backend settings/accounts/proxy/usage/auth clients, new proxy-profiles module, Docker sidecar assets
- Data: new `proxy_profiles` table, new proxy assignment fields on `accounts`, new default profile field on `dashboard_settings`
- Frontend: Settings and Accounts pages
- Tests: backend unit/integration and frontend component coverage
