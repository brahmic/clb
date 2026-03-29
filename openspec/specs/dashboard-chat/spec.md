# dashboard-chat Specification

## Purpose
Provide an operator-only chat workspace inside the authenticated dashboard for testing routed model requests against the same account pool used by the proxy.

## Requirements
### Requirement: Authenticated dashboard chat streaming endpoint

The system SHALL expose `POST /api/dashboard-chat/responses` as a dashboard-session-protected `text/event-stream` endpoint. The request body MUST accept `accountId`, `model`, `reasoningEffort`, and `messages`, where each message contains `role` plus text and optional user image parts. If `accountId` is provided but does not reference an active account, the endpoint MUST return `400` with dashboard error code `invalid_account_selection`.

#### Scenario: Unauthenticated request is rejected
- **WHEN** a client calls `POST /api/dashboard-chat/responses` without a valid dashboard session
- **THEN** the system returns `401` with the dashboard auth error envelope

#### Scenario: Non-active account selection is rejected
- **WHEN** a client calls `POST /api/dashboard-chat/responses` with `accountId` that is missing or not `active`
- **THEN** the system returns `400` with `error.code = "invalid_account_selection"`

#### Scenario: User image input is accepted
- **WHEN** a request includes a `user` message containing an image part with a data URL
- **THEN** the system maps that part to upstream `input_image`

### Requirement: Dashboard chat routing semantics

The dashboard chat endpoint SHALL reuse the existing proxy pipeline and preserve its normalized upstream response events. Before forwarding upstream stream events, the endpoint MUST emit a `dashboard.chat.started` event containing `mode`, `requestedAccountId`, and `resolvedAccountId`.

If `accountId` is `null`, the system MUST route using the existing automatic load-balancer account selection semantics.

If `accountId` is set, the system MUST pin the request to that active account and MUST NOT fail over to a different account when the pinned attempt returns an upstream rate-limit, auth, or other upstream error.

#### Scenario: Auto mode emits routing metadata
- **WHEN** a request omits `accountId`
- **THEN** the first SSE event is `dashboard.chat.started` with `mode = "auto"`
- **AND** later SSE events remain the proxy's normalized response events

#### Scenario: Explicit account selection stays pinned
- **WHEN** a request sets `accountId` to an active account and the upstream attempt fails
- **THEN** the stream reports the failure for that same account
- **AND** the system does not retry the request on a different account

### Requirement: Dashboard images streaming endpoint

The system SHALL expose `POST /api/dashboard-images/conversation` as a dashboard-session-protected `text/event-stream` endpoint dedicated to ChatGPT product image generation and transformation. The request body MUST accept `accountId`, `model`, `conversationId`, `parentMessageId`, `prompt`, `attachments`, and `editTarget`.

If `accountId` is `null`, the endpoint MUST use the same automatic account-selection semantics as dashboard chat. If `accountId` is set, the endpoint MUST pin the request to that active account and MUST NOT fail over to a different account when the pinned attempt fails upstream.

The endpoint MUST emit dashboard-specific SSE events:
- `dashboard.images.started`
- `dashboard.images.progress`
- `dashboard.images.completed`
- `dashboard.images.failed`

#### Scenario: Image route is authenticated
- **WHEN** a client calls `POST /api/dashboard-images/conversation` without a valid dashboard session
- **THEN** the system returns `401` with the dashboard auth error envelope

#### Scenario: Image route rejects non-active account selection
- **WHEN** a client calls `POST /api/dashboard-images/conversation` with `accountId` that is missing or not `active`
- **THEN** the system returns `400` with `error.code = "invalid_account_selection"`

#### Scenario: Auto image mode emits routing metadata
- **WHEN** a client omits `accountId` on `POST /api/dashboard-images/conversation`
- **THEN** the first SSE event is `dashboard.images.started` with `mode = "auto"`

#### Scenario: Explicit image account selection stays pinned
- **WHEN** a client sets `accountId` to an active account and the upstream image attempt fails
- **THEN** the stream reports `dashboard.images.failed` for that same account
- **AND** the system does not retry the request on a different account

### Requirement: ChatGPT image pipeline

The dashboard images endpoint SHALL use the ChatGPT product image flow instead of the `codex/responses` route. The system MUST upload local browser images through ChatGPT file endpoints, submit image turns through `backend-api/f/conversation`, poll async image status, and fetch generated files as stable inline data for the SPA.

Prompt-only image turns MUST create new images. Prompt plus uploaded reference images MUST create image transformations from those references. Follow-up edits of a previously generated image MUST send transformation metadata using the persisted generated-image identifiers from the prior turn.

#### Scenario: Reference images are uploaded before the image turn
- **WHEN** an image-thread request includes local attachments
- **THEN** the system uploads those files through ChatGPT file endpoints
- **AND** maps them into the conversation payload as `image_asset_pointer` parts with matching attachment metadata

#### Scenario: Edit follow-up uses original generation metadata
- **WHEN** an image-thread request includes `editTarget`
- **THEN** the system sends ChatGPT transformation metadata containing the stored `originalGenId` and `fileId`

#### Scenario: Completed image turn returns inline generated assets
- **WHEN** ChatGPT finishes the image job successfully
- **THEN** the system emits `dashboard.images.completed`
- **AND** the event includes `conversationId`, `assistantMessageId`, `parentMessageId`, and generated images as inline data plus persisted edit metadata

### Requirement: Dashboard chat workspace

The authenticated SPA SHALL expose a top-level `/chat` route in dashboard navigation. The chat page MUST provide:
- a local thread switcher with `New chat`
- a model selector populated from `/api/models`
- an account selector containing `Auto routing` plus only active accounts from `/api/accounts`
- an explicit thread-mode selector with `Chat` and `ChatGPT Images`
- a transcript area that streams assistant output in place
- a composer that supports multiline text, `Enter` to send, `Shift+Enter` for a newline, and image attachments

The page MUST show the resolved serving account from `dashboard.chat.started` or `dashboard.images.started` for the active thread.

#### Scenario: Chat route is protected
- **WHEN** an unauthenticated browser navigates to `/chat`
- **THEN** the dashboard auth flow redirects the browser to `/login`

#### Scenario: Account selector excludes inactive accounts
- **WHEN** the chat page renders with a mix of active and paused accounts
- **THEN** the selector shows `Auto routing` plus only the active accounts

#### Scenario: Operator sends text and image in one turn
- **WHEN** the operator attaches an image and submits text from the composer
- **THEN** the transcript shows both inputs in the user turn
- **AND** the assistant response streams into the same thread

#### Scenario: Operator generates an image
- **WHEN** the operator switches the thread to `ChatGPT Images` and submits a prompt
- **THEN** the assistant transcript renders the generated image inline
- **AND** the generated image can be opened or downloaded from the transcript

#### Scenario: Operator edits a generated image
- **WHEN** the operator clicks `Edit` on a generated image and submits a follow-up prompt
- **THEN** the next image turn uses the selected generated asset as the edit target
- **AND** the updated generated image appears in the same local thread

### Requirement: Browser-local chat persistence

The SPA SHALL persist dashboard chat threads in browser storage only. Thread history MUST be stored in IndexedDB, capped to the 20 most recent threads. The active thread id, last selected model, last routing mode, and last thread mode MUST be stored separately in `localStorage`.

#### Scenario: Reload restores recent threads
- **WHEN** the operator refreshes `/chat`
- **THEN** the page restores saved local threads from IndexedDB
- **AND** restores the active thread, last selected model, and last routing mode from browser storage

#### Scenario: Stream is not resumed after reload
- **WHEN** the operator refreshes the page during an in-flight stream
- **THEN** the previous local thread remains visible after reload
- **AND** the in-flight stream is not resumed automatically
