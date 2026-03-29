# Dashboard Chat Context

`dashboard-chat` is an operator tool inside the admin UI, not a public end-user chat product.

Key decisions:
- Reuse the existing proxy pipeline instead of creating a second model client stack.
- Keep explicit account pinning available only on dashboard-authenticated routes; public `/v1` and backend Codex routes keep ignoring inbound account override headers.
- Store chat threads only in the browser for MVP so the feature does not add new database tables, retention policy, or multi-user data ownership concerns.

Example:
- `Auto routing` lets an operator inspect how the normal load balancer answers a prompt.
- Choosing a specific active account lets the operator test one account directly and confirm whether failures belong to that account instead of being masked by failover.
