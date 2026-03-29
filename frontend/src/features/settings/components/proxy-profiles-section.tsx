import { useMemo, useState } from "react";
import { Network } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { buildSettingsUpdateRequest } from "@/features/settings/payload";
import type { DashboardSettings, SettingsUpdateRequest } from "@/features/settings/schemas";
import { ProxyProfileDialog } from "@/features/settings/components/proxy-profile-dialog";
import { useProxyProfiles } from "@/features/proxy-profiles/hooks/use-proxy-profiles";
import type { ProxyProfile, ProxyProfileStatus } from "@/features/proxy-profiles/schemas";
import { cn } from "@/lib/utils";

type ProxyProfilesSectionProps = {
  settings: DashboardSettings;
  busy: boolean;
  onSaveSettings: (payload: SettingsUpdateRequest) => Promise<void>;
};

function transportLabel(profile: ProxyProfile) {
  if (profile.transportKind === "reality_tcp") {
    return "Reality/TCP";
  }
  if (profile.transportKind === "tls_tcp") {
    return "TLS/TCP";
  }
  return "WS/TLS";
}

function statusBadgeProps(status: ProxyProfileStatus | undefined, checking: boolean) {
  if (checking && !status) {
    return { label: "Checking", className: "border-border text-muted-foreground" };
  }
  if (!status) {
    return { label: "Unknown", className: "border-border text-muted-foreground" };
  }
  if (status.status === "ok") {
    return {
      label: "Connected",
      className: "border-emerald-200 bg-emerald-500/10 text-emerald-700 dark:border-emerald-900 dark:text-emerald-300",
    };
  }
  return {
    label: "Error",
    className: "border-destructive/20 bg-destructive/10 text-destructive",
  };
}

export function ProxyProfilesSection({ settings, busy, onSaveSettings }: ProxyProfilesSectionProps) {
  const { profilesQuery, statusesQuery, createMutation, updateMutation, deleteMutation } = useProxyProfiles({
    includeStatuses: true,
  });
  const profiles = profilesQuery.data ?? [];
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingProfile, setEditingProfile] = useState<ProxyProfile | null>(null);

  const mutationBusy = busy || createMutation.isPending || updateMutation.isPending || deleteMutation.isPending;
  const statusBusy = statusesQuery.isFetching;
  const defaultConnectionValue = settings.defaultProxyProfileId ?? "direct";
  const byId = useMemo(() => new Map(profiles.map((profile) => [profile.id, profile])), [profiles]);
  const statusesById = useMemo(
    () => new Map((statusesQuery.data ?? []).map((status) => [status.profileId, status])),
    [statusesQuery.data],
  );

  return (
    <section className="rounded-xl border bg-card p-5">
      <div className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
              <Network className="h-4 w-4 text-primary" aria-hidden="true" />
            </div>
            <div>
              <h3 className="text-sm font-semibold">Proxy Profiles</h3>
              <p className="text-xs text-muted-foreground">
                Manage encrypted VLESS connections for account-bound traffic.
              </p>
            </div>
          </div>
          <Button
            type="button"
            size="sm"
            onClick={() => {
              setEditingProfile(null);
              setDialogOpen(true);
            }}
            disabled={mutationBusy}
          >
            Add profile
          </Button>
        </div>

        <div className="rounded-lg border">
          <div className="flex items-center justify-between gap-4 border-b p-3">
            <div>
              <p className="text-sm font-medium">Default connection</p>
              <p className="text-xs text-muted-foreground">Inherited accounts use this connection.</p>
            </div>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={statusBusy || profiles.length === 0}
                onClick={() => void statusesQuery.refetch()}
              >
                Refresh status
              </Button>
              <Select
                value={defaultConnectionValue}
                onValueChange={(value) =>
                  void onSaveSettings(
                    buildSettingsUpdateRequest(settings, {
                      defaultProxyProfileId: value === "direct" ? null : value,
                    }),
                  )
                }
              >
                <SelectTrigger className="h-8 w-52 text-xs" disabled={mutationBusy}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="end">
                  <SelectItem value="direct">Direct</SelectItem>
                  {profiles.map((profile) => (
                    <SelectItem key={profile.id} value={profile.id}>
                      {profile.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="divide-y">
            {profiles.length === 0 ? (
              <div className="p-3 text-sm text-muted-foreground">No proxy profiles configured.</div>
            ) : (
              profiles.map((profile) => {
                const isDefault = settings.defaultProxyProfileId === profile.id;
                const status = statusesById.get(profile.id);
                const badge = statusBadgeProps(status, statusBusy);
                return (
                  <div key={profile.id} className="flex items-center justify-between gap-4 p-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-medium">{profile.name}</p>
                        {isDefault ? <span className="text-xs text-primary">Default</span> : null}
                        <Badge variant="outline" className={cn("rounded-md px-1.5 py-0 text-[11px]", badge.className)}>
                          {badge.label}
                        </Badge>
                      </div>
                      <p className="truncate text-xs text-muted-foreground">
                        {transportLabel(profile)} · {profile.serverHost}:{profile.serverPort} · local:{profile.localProxyPort}
                      </p>
                      {status?.egressIp ? (
                        <p className="truncate text-xs text-muted-foreground">
                          IP {status.egressIp}
                          {typeof status.latencyMs === "number" ? ` · ${status.latencyMs} ms` : ""}
                        </p>
                      ) : null}
                      {status?.lastError ? (
                        <p className="truncate text-xs text-destructive/90">{status.lastError}</p>
                      ) : null}
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={mutationBusy}
                        onClick={() => {
                          setEditingProfile(profile);
                          setDialogOpen(true);
                        }}
                      >
                        Edit
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={mutationBusy}
                        onClick={() => void deleteMutation.mutateAsync(profile.id)}
                      >
                        Delete
                      </Button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        <p className="text-xs text-muted-foreground">
          Supported: `VLESS Reality/TCP`, `VLESS WS/TLS`, and `VLESS TCP/TLS`. Changes affect only account-bound traffic.
        </p>
      </div>

      <ProxyProfileDialog
        open={dialogOpen}
        profile={editingProfile ? byId.get(editingProfile.id) ?? editingProfile : null}
        busy={mutationBusy}
        onOpenChange={setDialogOpen}
        onSave={async (payload) => {
          if (editingProfile) {
            await updateMutation.mutateAsync({ profileId: editingProfile.id, payload });
          } else {
            if (!payload.vlessUri) {
              return;
            }
            await createMutation.mutateAsync({ name: payload.name, vlessUri: payload.vlessUri });
          }
          setDialogOpen(false);
        }}
      />
    </section>
  );
}
