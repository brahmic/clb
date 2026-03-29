import type { DashboardSettings, SettingsUpdateRequest } from "@/features/settings/schemas";

export function buildSettingsUpdateRequest(
  settings: DashboardSettings,
  patch: Partial<SettingsUpdateRequest>,
): SettingsUpdateRequest {
  return {
    stickyThreadsEnabled: settings.stickyThreadsEnabled,
    upstreamStreamTransport: settings.upstreamStreamTransport,
    defaultProxyProfileId: settings.defaultProxyProfileId ?? null,
    preferEarlierResetAccounts: settings.preferEarlierResetAccounts,
    routingStrategy: settings.routingStrategy,
    openaiCacheAffinityMaxAgeSeconds: settings.openaiCacheAffinityMaxAgeSeconds,
    importWithoutOverwrite: settings.importWithoutOverwrite,
    totpRequiredOnLogin: settings.totpRequiredOnLogin,
    apiKeyAuthEnabled: settings.apiKeyAuthEnabled,
    ...patch,
  };
}
