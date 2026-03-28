import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getAuthSession,
  loginPassword,
  logout as logoutRequest,
  setupPassword as setupPasswordRequest,
  verifyTotp as verifyTotpRequest,
} from "@/features/auth/api";
import { useAuthStore } from "@/features/auth/hooks/use-auth";
import type { AuthSession } from "@/features/auth/schemas";

vi.mock("@/features/auth/api", () => ({
  getAuthSession: vi.fn(),
  loginPassword: vi.fn(),
  logout: vi.fn(),
  setupPassword: vi.fn(),
  verifyTotp: vi.fn(),
}));

const sessionBase: AuthSession = {
  authenticated: true,
  setupRequired: false,
  passwordRequired: true,
  totpRequiredOnLogin: false,
  totpConfigured: true,
};

function resetAuthStore(): void {
  useAuthStore.setState({
    setupRequired: false,
    passwordRequired: false,
    authenticated: false,
    totpRequiredOnLogin: false,
    totpConfigured: false,
    loading: false,
    initialized: false,
    error: null,
  });
}

describe("useAuthStore actions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetAuthStore();
  });

  it("refreshSession tracks bootstrap-required state", async () => {
    vi.mocked(getAuthSession).mockResolvedValue({
      authenticated: false,
      setupRequired: true,
      passwordRequired: false,
      totpRequiredOnLogin: false,
      totpConfigured: false,
    });

    await useAuthStore.getState().refreshSession();

    const next = useAuthStore.getState();
    expect(next.setupRequired).toBe(true);
    expect(next.authenticated).toBe(false);
  });

  it("refreshSession updates auth state", async () => {
    vi.mocked(getAuthSession).mockResolvedValue({
      ...sessionBase,
      authenticated: false,
      totpRequiredOnLogin: true,
    });

    await useAuthStore.getState().refreshSession();

    const next = useAuthStore.getState();
    expect(next.initialized).toBe(true);
    expect(next.authenticated).toBe(false);
    expect(next.totpRequiredOnLogin).toBe(true);
    expect(next.loading).toBe(false);
  });

  it("setupPassword updates session state", async () => {
    vi.mocked(setupPasswordRequest).mockResolvedValue(sessionBase);

    await useAuthStore.getState().setupPassword("secret-pass");

    const next = useAuthStore.getState();
    expect(setupPasswordRequest).toHaveBeenCalledWith({ password: "secret-pass" });
    expect(next.authenticated).toBe(true);
    expect(next.setupRequired).toBe(false);
  });

  it("login updates session state", async () => {
    vi.mocked(loginPassword).mockResolvedValue(sessionBase);

    await useAuthStore.getState().login("secret-pass");

    const next = useAuthStore.getState();
    expect(loginPassword).toHaveBeenCalledWith({ password: "secret-pass" });
    expect(next.authenticated).toBe(true);
    expect(next.error).toBeNull();
  });

  it("logout clears auth and refreshes session", async () => {
    useAuthStore.setState({
      authenticated: true,
      passwordRequired: true,
      initialized: true,
    });

    vi.mocked(logoutRequest).mockResolvedValue({ status: "ok" });
    vi.mocked(getAuthSession).mockResolvedValue({
      ...sessionBase,
      authenticated: false,
      setupRequired: false,
      totpRequiredOnLogin: false,
    });

    await useAuthStore.getState().logout();

    const next = useAuthStore.getState();
    expect(logoutRequest).toHaveBeenCalledTimes(1);
    expect(getAuthSession).toHaveBeenCalledTimes(1);
    expect(next.authenticated).toBe(false);
    expect(next.loading).toBe(false);
  });

  it("verifyTotp updates state transitions", async () => {
    vi.mocked(verifyTotpRequest).mockResolvedValue({
      ...sessionBase,
      authenticated: true,
      setupRequired: false,
      totpRequiredOnLogin: false,
    });

    await useAuthStore.getState().verifyTotp("123456");

    const next = useAuthStore.getState();
    expect(verifyTotpRequest).toHaveBeenCalledWith({ code: "123456" });
    expect(next.authenticated).toBe(true);
    expect(next.totpRequiredOnLogin).toBe(false);
    expect(next.loading).toBe(false);
  });
});
