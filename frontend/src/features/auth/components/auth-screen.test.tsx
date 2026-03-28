import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { AuthScreen } from "@/features/auth/components/auth-screen";
import { useAuthStore } from "@/features/auth/hooks/use-auth";

function setAuthState(
  patch: Partial<ReturnType<typeof useAuthStore.getState>>,
): void {
  useAuthStore.setState({
    initialized: true,
    loading: false,
    setupRequired: false,
    passwordRequired: true,
    authenticated: false,
    totpRequiredOnLogin: false,
    totpConfigured: false,
    error: null,
    ...patch,
  });
}

describe("AuthScreen", () => {
  beforeEach(() => {
    setAuthState({});
  });

  it("shows the setup form when bootstrap is required", () => {
    setAuthState({
      setupRequired: true,
      passwordRequired: false,
    });

    render(
      <MemoryRouter>
        <AuthScreen />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "Set admin password" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set Password" })).toBeInTheDocument();
  });

  it("shows the TOTP prompt when password login is pending step-up", () => {
    setAuthState({
      totpRequiredOnLogin: true,
      passwordRequired: true,
    });

    render(
      <MemoryRouter>
        <AuthScreen />
      </MemoryRouter>,
    );

    expect(screen.getByText("Two-factor verification")).toBeInTheDocument();
  });

  it("redirects authenticated users away from /login", () => {
    setAuthState({
      authenticated: true,
      passwordRequired: true,
    });

    render(
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<AuthScreen />} />
          <Route path="/dashboard" element={<div>Dashboard route</div>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText("Dashboard route")).toBeInTheDocument();
  });
});
