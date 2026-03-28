import type { PropsWithChildren } from "react";
import { Navigate } from "react-router-dom";

import { SpinnerBlock } from "@/components/ui/spinner";
import { useAuthStore } from "@/features/auth/hooks/use-auth";

export function AuthGate({ children }: PropsWithChildren) {
  const initialized = useAuthStore((state) => state.initialized);
  const authenticated = useAuthStore((state) => state.authenticated);

  if (!initialized) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <SpinnerBlock />
      </div>
    );
  }

  if (!authenticated) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}
