## 1. Confirm the blocker precisely

- [ ] 1.1 Capture a minimal reproducible trace showing `prepare` succeeds and `f/conversation` returns a Cloudflare challenge page from the Docker browser worker.
- [ ] 1.2 Record the exact worker/browser/runtime characteristics that were tested: headful Chromium, Xvfb, colocated `xray-client`, stored account credentials.

## 2. Decide whether the Docker browser path is salvageable

- [ ] 2.1 Run a bounded set of runtime experiments on the single supported transport only; do not reintroduce host-worker or cookie-paste paths.
- [ ] 2.2 Stop if the path remains blocked after those experiments and document that ChatGPT-web-backed images are not viable in this architecture.

## 3. Choose the long-term direction

- [ ] 3.1 Either hard-disable `ChatGPT Images` in the product until a supported path exists, or
- [ ] 3.2 Replace the upstream with a supported image backend/API while keeping the dashboard UX and normal text-chat routing intact.
