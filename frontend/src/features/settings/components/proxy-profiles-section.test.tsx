import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProxyProfilesSection } from "@/features/settings/components/proxy-profiles-section";
import { useProxyProfiles } from "@/features/proxy-profiles/hooks/use-proxy-profiles";
import type { DashboardSettings } from "@/features/settings/schemas";

vi.mock("@/features/proxy-profiles/hooks/use-proxy-profiles", () => ({
  useProxyProfiles: vi.fn(),
}));

const useProxyProfilesMock = vi.mocked(useProxyProfiles);

const BASE_SETTINGS: DashboardSettings = {
  stickyThreadsEnabled: false,
  upstreamStreamTransport: "default",
  defaultProxyProfileId: null,
  preferEarlierResetAccounts: false,
  routingStrategy: "usage_weighted",
  openaiCacheAffinityMaxAgeSeconds: 300,
  importWithoutOverwrite: false,
  totpRequiredOnLogin: false,
  totpConfigured: false,
  apiKeyAuthEnabled: false,
};

describe("ProxyProfilesSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders saved profiles and highlights the default connection", () => {
    useProxyProfilesMock.mockReturnValue({
      profilesQuery: {
        data: [
          {
            id: "profile-1",
            name: "Primary",
            protocol: "vless",
            transportKind: "reality_tcp",
            serverHost: "reality.example.com",
            serverPort: 443,
            localProxyPort: 20080,
          },
        ],
      },
      statusesQuery: {
        data: [
          {
            profileId: "profile-1",
            status: "ok",
            egressIp: "203.0.113.5",
            lastError: null,
            checkedAt: "2026-01-01T00:00:00Z",
            latencyMs: 148,
          },
        ],
        isFetching: false,
        refetch: vi.fn().mockResolvedValue(undefined),
      },
      createMutation: { isPending: false },
      updateMutation: { isPending: false },
      deleteMutation: { isPending: false, mutateAsync: vi.fn().mockResolvedValue(undefined) },
    } as never);

    render(
      <ProxyProfilesSection
        settings={{ ...BASE_SETTINGS, defaultProxyProfileId: "profile-1" }}
        busy={false}
        onSaveSettings={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.getByText("Proxy Profiles")).toBeInTheDocument();
    expect(screen.getAllByText("Primary").length).toBeGreaterThan(0);
    expect(screen.getByText("Default")).toBeInTheDocument();
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.getByText(/Reality\/TCP .*reality\.example\.com.*443.*local:20080/)).toBeInTheDocument();
    expect(screen.getByText("IP 203.0.113.5 · 148 ms")).toBeInTheDocument();
  });

  it("creates a new proxy profile from the dialog", async () => {
    const user = userEvent.setup();
    const createMutation = {
      isPending: false,
      mutateAsync: vi.fn().mockResolvedValue(undefined),
    };

    useProxyProfilesMock.mockReturnValue({
      profilesQuery: { data: [] },
      statusesQuery: {
        data: [],
        isFetching: false,
        refetch: vi.fn().mockResolvedValue(undefined),
      },
      createMutation,
      updateMutation: { isPending: false },
      deleteMutation: { isPending: false, mutateAsync: vi.fn().mockResolvedValue(undefined) },
    } as never);

    render(
      <ProxyProfilesSection
        settings={BASE_SETTINGS}
        busy={false}
        onSaveSettings={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Add profile" }));
    await user.type(screen.getByLabelText("Name"), "Proxy A");
    await user.type(
      screen.getByLabelText("VLESS URI"),
      "vless://11111111-1111-1111-1111-111111111111@reality.example.com:443?type=tcp&security=reality&sni=cdn.example.com&pbk=PUBLICKEY123",
    );
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(createMutation.mutateAsync).toHaveBeenCalledWith({
        name: "Proxy A",
        vlessUri:
          "vless://11111111-1111-1111-1111-111111111111@reality.example.com:443?type=tcp&security=reality&sni=cdn.example.com&pbk=PUBLICKEY123",
      });
    });
  });
});
