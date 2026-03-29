## MODIFIED Requirements

### Requirement: Settings page sections
The Settings page SHALL include sections for: routing settings, proxy profile management, password management, TOTP management, API key management, and sticky-session administration.

#### Scenario: Manage proxy profiles
- **WHEN** a user opens Settings
- **THEN** the page shows a Proxy Profiles section with a profile list, create/edit actions, and a default connection selector that supports `Direct` plus saved profiles

### Requirement: Accounts page detail actions
The Accounts page SHALL support per-account connection assignment from the detail pane.

#### Scenario: Assign account connection
- **WHEN** a user selects an account and changes its connection mode to `inherit default`, `direct`, or `specific profile`
- **THEN** the app persists that assignment through the accounts API
- **AND** the updated account detail reflects the chosen mode without requiring navigation away from the page
