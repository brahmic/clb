# Dashboard Chat Context

`dashboard-chat` is an operator tool inside the admin UI, not a public end-user chat product.

Key decisions:
- Reuse the existing proxy pipeline for normal text chat, but use a dedicated ChatGPT product client for image threads because ChatGPT image generation/editing does not run on `codex/responses`.
- Keep explicit account pinning available only on dashboard-authenticated routes; public `/v1` and backend Codex routes keep ignoring inbound account override headers.
- Store chat threads only in the browser for MVP so the feature does not add new database tables, retention policy, or multi-user data ownership concerns.
- Keep image threads inside `/chat`, but back them with a separate ChatGPT product pipeline instead of the normal `Responses` transport.
- Treat image generation and transformation as explicit thread mode, not prompt inference, so operators can predict which upstream path the UI will use.
- Persist generated-image `fileId` / `originalGenId` metadata in browser storage so follow-up edit turns can reuse the same ChatGPT conversation state without adding database tables.

Example:
- `Auto routing` lets an operator inspect how the normal load balancer answers a prompt.
- Choosing a specific active account lets the operator test one account directly and confirm whether failures belong to that account instead of being masked by failover.
- Switching a thread to `ChatGPT Images` routes the turn through ChatGPT file upload plus `f/conversation`, then renders the generated image inline in the same local thread.
