import { useEffect, useState } from "react";
import { Bot, Link2Off, Sparkles } from "lucide-react";

import { AlertMessage } from "@/components/alert-message";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { AccountSummary } from "@/features/accounts/schemas";
import { getErrorMessageOrNull } from "@/utils/errors";

type AccountChatGPTImageSessionSettingsProps = {
  account: AccountSummary;
  busy: boolean;
  disconnectError: Error | null;
  credentialsError: Error | null;
  clearCredentialsError: Error | null;
  onDisconnect: (accountId: string) => Promise<void>;
  onSaveCredentials: (accountId: string, payload: { loginEmail: string; password: string }) => Promise<void>;
  onClearCredentials: (accountId: string) => Promise<void>;
};

function statusLabel(status: string | undefined): string {
  switch (status) {
    case "ready":
      return "Ready";
    case "error":
      return "Error";
    default:
      return "Disconnected";
  }
}

export function AccountChatGPTImageSessionSettings({
  account,
  busy,
  disconnectError,
  credentialsError,
  clearCredentialsError,
  onDisconnect,
  onSaveCredentials,
  onClearCredentials,
}: AccountChatGPTImageSessionSettingsProps) {
  const session = account.chatgptImageSession;
  const credentials = account.chatgptImageCredentials;
  const sessionStatus = session?.status ?? "disconnected";
  const [loginEmail, setLoginEmail] = useState(credentials?.loginEmail ?? account.email);
  const [password, setPassword] = useState("");

  useEffect(() => {
    setLoginEmail(credentials?.loginEmail ?? account.email);
    setPassword("");
  }, [account.accountId, account.email, credentials?.loginEmail]);

  const error =
    getErrorMessageOrNull(credentialsError) ||
    getErrorMessageOrNull(clearCredentialsError) ||
    getErrorMessageOrNull(disconnectError);

  return (
    <div className="space-y-4 rounded-lg border bg-muted/30 p-4">
      <div className="flex items-start gap-2">
        <Bot className="mt-0.5 h-4 w-4 text-primary" />
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            ChatGPT Images Automation
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Save ChatGPT login credentials once. The image worker will bootstrap and refresh the browser session
            automatically when image mode needs it.
          </p>
        </div>
      </div>

      {error ? <AlertMessage variant="error">{error}</AlertMessage> : null}
      {session?.lastError ? <AlertMessage variant="error">{session.lastError}</AlertMessage> : null}

      <dl className="grid gap-2 text-xs sm:grid-cols-4">
        <div className="rounded-md border bg-background px-3 py-2">
          <dt className="text-muted-foreground">Session</dt>
          <dd className="mt-1 font-medium">{statusLabel(sessionStatus)}</dd>
        </div>
        <div className="rounded-md border bg-background px-3 py-2">
          <dt className="text-muted-foreground">Validated</dt>
          <dd className="mt-1 font-medium">
            {session?.lastValidatedAt ? new Date(session.lastValidatedAt).toLocaleString() : "Never"}
          </dd>
        </div>
        <div className="rounded-md border bg-background px-3 py-2">
          <dt className="text-muted-foreground">Automation</dt>
          <dd className="mt-1 font-medium">{credentials?.configured ? "Configured" : "Missing"}</dd>
        </div>
        <div className="rounded-md border bg-background px-3 py-2">
          <dt className="text-muted-foreground">Credentials Updated</dt>
          <dd className="mt-1 font-medium">
            {credentials?.updatedAt ? new Date(credentials.updatedAt).toLocaleString() : "Never"}
          </dd>
        </div>
      </dl>

      <form
        className="space-y-3 rounded-md border bg-background p-3"
        onSubmit={(event) => {
          event.preventDefault();
          void onSaveCredentials(account.accountId, { loginEmail, password });
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-xs">
            <span className="text-muted-foreground">Login email</span>
            <Input
              value={loginEmail}
              onChange={(event) => setLoginEmail(event.target.value)}
              autoComplete="username"
              placeholder="name@example.com"
              disabled={busy}
            />
          </label>
          <label className="space-y-1 text-xs">
            <span className="text-muted-foreground">Password</span>
            <Input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              placeholder={credentials?.configured ? "Saved. Enter to replace." : "ChatGPT password"}
              disabled={busy}
            />
          </label>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button type="submit" size="sm" className="h-8 gap-1.5 text-xs" disabled={busy || !loginEmail.trim() || !password.trim()}>
            <Sparkles className="h-3.5 w-3.5" />
            {credentials?.configured ? "Update automation" : "Save automation"}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 gap-1.5 text-xs"
            disabled={busy || !credentials?.configured}
            onClick={() => {
              void onClearCredentials(account.accountId);
            }}
          >
            <Link2Off className="h-3.5 w-3.5" />
            Clear automation
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 gap-1.5 text-xs"
            disabled={busy || sessionStatus === "disconnected"}
            onClick={() => {
              void onDisconnect(account.accountId);
            }}
          >
            <Link2Off className="h-3.5 w-3.5" />
            Disconnect session
          </Button>
        </div>
      </form>
    </div>
  );
}
