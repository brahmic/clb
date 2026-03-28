import { Navigate } from "react-router-dom";
import type { ReactNode } from "react";

import { CodexLogo } from "@/components/brand/codex-logo";
import { SpinnerBlock } from "@/components/ui/spinner";
import { LoginForm } from "@/features/auth/components/login-form";
import { TotpDialog } from "@/features/auth/components/totp-dialog";
import { useAuthStore } from "@/features/auth/hooks/use-auth";

function AuthScreenShell({ children }: { children: ReactNode }) {
  return (
    <div className="relative flex min-h-screen items-center justify-center p-4">
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -top-1/4 -right-1/4 h-[600px] w-[600px] rounded-full bg-primary/5 blur-3xl" />
        <div className="absolute -bottom-1/4 -left-1/4 h-[500px] w-[500px] rounded-full bg-primary/3 blur-3xl" />
        <div className="absolute bottom-0 left-1/2 h-[400px] w-[400px] -translate-x-1/2 rounded-full bg-primary/4 blur-3xl" />
      </div>

      <div className="relative w-full max-w-sm animate-fade-in-up">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 shadow-sm ring-2 ring-primary/10 ring-offset-2 ring-offset-background">
            <CodexLogo size={28} className="text-primary" />
          </div>
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Codex Modex</h1>
            <p className="mt-0.5 text-sm text-muted-foreground">API Load Balancer</p>
          </div>
        </div>
        {children}
      </div>
    </div>
  );
}

export function AuthScreen() {
  const initialized = useAuthStore((state) => state.initialized);
  const authenticated = useAuthStore((state) => state.authenticated);
  const setupRequired = useAuthStore((state) => state.setupRequired);
  const totpRequiredOnLogin = useAuthStore((state) => state.totpRequiredOnLogin);

  if (!initialized) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <SpinnerBlock />
      </div>
    );
  }

  if (authenticated) {
    return <Navigate to="/dashboard" replace />;
  }

  if (totpRequiredOnLogin) {
    return (
      <AuthScreenShell>
        <TotpDialog open />
      </AuthScreenShell>
    );
  }

  return (
    <AuthScreenShell>
      <LoginForm mode={setupRequired ? "setup" : "login"} />
    </AuthScreenShell>
  );
}
