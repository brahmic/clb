import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { AuthGate } from "@/features/auth/components/auth-gate";
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
    error: null,
    ...patch,
  });
}

describe("AuthGate", () => {
  beforeEach(() => {
    setAuthState({});
  });

  it("redirects to login when unauthenticated", () => {
    setAuthState({
      passwordRequired: true,
      authenticated: false,
      totpRequiredOnLogin: false,
    });

    render(
      <MemoryRouter initialEntries={["/dashboard"]}>
        <Routes>
          <Route
            path="/dashboard"
            element={
              <AuthGate>
                <div>Protected content</div>
              </AuthGate>
            }
          />
          <Route path="/login" element={<div>Login route</div>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText("Login route")).toBeInTheDocument();
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
  });

  it("shows children when authenticated", () => {
    setAuthState({
      passwordRequired: true,
      authenticated: true,
      totpRequiredOnLogin: false,
    });

    render(
      <MemoryRouter>
        <AuthGate>
          <div>Protected content</div>
        </AuthGate>
      </MemoryRouter>,
    );

    expect(screen.getByText("Protected content")).toBeInTheDocument();
  });

  it("redirects setup-required sessions to login", () => {
    setAuthState({
      setupRequired: true,
      passwordRequired: false,
      authenticated: false,
      totpRequiredOnLogin: false,
    });

    render(
      <MemoryRouter initialEntries={["/dashboard"]}>
        <Routes>
          <Route
            path="/dashboard"
            element={
              <AuthGate>
                <div>Protected content</div>
              </AuthGate>
            }
          />
          <Route path="/login" element={<div>Login route</div>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText("Login route")).toBeInTheDocument();
  });
});
