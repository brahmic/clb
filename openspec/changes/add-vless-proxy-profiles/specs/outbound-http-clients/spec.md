## MODIFIED Requirements

### Requirement: Outbound aiohttp clients honor environment proxy settings
Shared outbound `aiohttp` clients MUST honor `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY` environment variables so operator-configured proxy routing applies consistently to upstream OAuth, proxy, and metadata calls.

#### Scenario: Account-bound traffic uses an explicit proxy profile instead of env defaults
- **WHEN** an account-bound provider request, usage refresh, or token refresh resolves a saved proxy profile
- **THEN** the request uses the explicit profile proxy endpoint for that account
- **AND** global direct flows continue using the existing direct or env-based behavior
