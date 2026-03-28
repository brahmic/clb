import { zodResolver } from "@hookform/resolvers/zod";
import { Lock } from "lucide-react";
import { useForm } from "react-hook-form";

import { AlertMessage } from "@/components/alert-message";
import { Button } from "@/components/ui/button";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { LoginRequestSchema, PasswordSetupRequestSchema } from "@/features/auth/schemas";
import { useAuthStore } from "@/features/auth/hooks/use-auth";

export type LoginFormProps = {
  mode?: "login" | "setup";
};

export function LoginForm({ mode = "login" }: LoginFormProps) {
  const login = useAuthStore((state) => state.login);
  const setupPassword = useAuthStore((state) => state.setupPassword);
  const loading = useAuthStore((state) => state.loading);
  const error = useAuthStore((state) => state.error);
  const clearError = useAuthStore((state) => state.clearError);

  const form = useForm({
    resolver: zodResolver(mode === "setup" ? PasswordSetupRequestSchema : LoginRequestSchema),
    defaultValues: { password: "" },
  });

  const handleSubmit = async (values: { password: string }) => {
    clearError();
    if (mode === "setup") {
      await setupPassword(values.password);
      return;
    }
    await login(values.password);
  };

  const title = mode === "setup" ? "Set admin password" : "Sign in";
  const description =
    mode === "setup"
      ? "Create the admin password before the dashboard can be used."
      : "Enter your admin password to continue.";
  const buttonLabel = mode === "setup" ? "Set Password" : "Sign In";
  const placeholder = mode === "setup" ? "Min. 8 characters" : "Enter password";

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(handleSubmit)} className="rounded-2xl border bg-card p-6 shadow-[var(--shadow-md)]">
        <div className="space-y-1.5">
          <h2 className="text-base font-semibold tracking-tight">{title}</h2>
          <p className="text-sm text-muted-foreground">{description}</p>
        </div>

        <div className="mt-5">
          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem>
                <FormLabel className="text-xs font-medium">Password</FormLabel>
                <div className="relative">
                  <Lock className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground/60" aria-hidden="true" />
                  <FormControl>
                    <Input
                      {...field}
                      type="password"
                      autoComplete={mode === "setup" ? "new-password" : "current-password"}
                      placeholder={placeholder}
                      disabled={loading}
                      className="pl-9"
                    />
                  </FormControl>
                </div>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>

        {error ? <AlertMessage variant="error" className="mt-4">{error}</AlertMessage> : null}

        <Button type="submit" className="press-scale mt-5 w-full" disabled={loading}>
          {loading ? <Spinner size="sm" className="mr-2" /> : null}
          {buttonLabel}
        </Button>
      </form>
    </Form>
  );
}
