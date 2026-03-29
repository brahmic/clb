import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { AccountSummary } from "@/features/accounts/schemas";
import type { ProxyProfile } from "@/features/proxy-profiles/schemas";

type AccountConnectionSettingsProps = {
  account: AccountSummary;
  profiles: ProxyProfile[];
  defaultProxyProfileId: string | null | undefined;
  busy: boolean;
  onSave: (payload: { mode: "inherit_default" | "direct" | "proxy_profile"; proxyProfileId?: string | null }) => Promise<void>;
};

function resolvedLabel(
  account: AccountSummary,
  profiles: ProxyProfile[],
  defaultProxyProfileId: string | null | undefined,
) {
  if (account.proxyAssignmentMode === "direct") {
    return "Direct";
  }
  if (account.proxyAssignmentMode === "proxy_profile") {
    const profile = profiles.find((entry) => entry.id === account.proxyProfileId);
    return profile ? `Profile: ${profile.name}` : "Profile: missing";
  }
  if (!defaultProxyProfileId) {
    return "Inherited: Direct";
  }
  const profile = profiles.find((entry) => entry.id === defaultProxyProfileId);
  return profile ? `Inherited: ${profile.name}` : "Inherited: Direct";
}

export function AccountConnectionSettings({
  account,
  profiles,
  defaultProxyProfileId,
  busy,
  onSave,
}: AccountConnectionSettingsProps) {
  const [mode, setMode] = useState<"inherit_default" | "direct" | "proxy_profile">(account.proxyAssignmentMode);
  const [profileId, setProfileId] = useState<string>(account.proxyProfileId ?? profiles[0]?.id ?? "");

  useEffect(() => {
    setMode(account.proxyAssignmentMode);
    setProfileId(account.proxyProfileId ?? profiles[0]?.id ?? "");
  }, [account.accountId, account.proxyAssignmentMode, account.proxyProfileId, profiles]);

  const changed =
    mode !== account.proxyAssignmentMode ||
    (mode === "proxy_profile" && (profileId || null) !== (account.proxyProfileId ?? null));
  const canSave = mode !== "proxy_profile" || profileId.length > 0;

  return (
    <section className="rounded-lg border p-4">
      <div className="mb-3">
        <h3 className="text-sm font-semibold">Connection</h3>
        <p className="mt-1 text-xs text-muted-foreground">{resolvedLabel(account, profiles, defaultProxyProfileId)}</p>
      </div>

      <div className="space-y-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-sm font-medium">Mode</p>
            <p className="text-xs text-muted-foreground">Choose default inheritance, direct, or a specific profile.</p>
          </div>
          <Select value={mode} onValueChange={(value) => setMode(value as typeof mode)}>
            <SelectTrigger className="h-8 w-52 text-xs" disabled={busy}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end">
              <SelectItem value="inherit_default">Inherit default</SelectItem>
              <SelectItem value="direct">Direct</SelectItem>
              <SelectItem value="proxy_profile">Specific profile</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {mode === "proxy_profile" ? (
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-medium">Profile</p>
              <p className="text-xs text-muted-foreground">Select one of the saved VLESS profiles.</p>
            </div>
            <Select value={profileId} onValueChange={setProfileId}>
              <SelectTrigger className="h-8 w-52 text-xs" disabled={busy}>
                <SelectValue placeholder="Select profile" />
              </SelectTrigger>
              <SelectContent align="end">
                {profiles.map((profile) => (
                  <SelectItem key={profile.id} value={profile.id}>
                    {profile.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        ) : null}

        <div className="flex justify-end">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={busy || !changed || !canSave}
            onClick={() =>
              void onSave({
                mode,
                proxyProfileId: mode === "proxy_profile" ? profileId : null,
              })
            }
          >
            Save connection
          </Button>
        </div>
      </div>
    </section>
  );
}
