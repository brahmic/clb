import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  deleteAccountChatGPTImageCredentials,
  deleteAccount,
  deleteAccountChatGPTImageSession,
  getAccountChatGPTImageCredentials,
  getAccountChatGPTImageSession,
  getAccountTrends,
  importAccount,
  listAccounts,
  pauseAccount,
  reactivateAccount,
  updateAccountChatGPTImageCredentials,
  updateAccountConnection,
} from "@/features/accounts/api";

function invalidateAccountRelatedQueries(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: ["accounts", "list"] });
  void queryClient.invalidateQueries({ queryKey: ["dashboard", "overview"] });
}

/**
 * Account mutation actions without the polling query.
 * Use this when you need account actions but already have account data
 * from another source (e.g. the dashboard overview query).
 */
export function useAccountMutations() {
  const queryClient = useQueryClient();

  const importMutation = useMutation({
    mutationFn: importAccount,
    onSuccess: () => {
      toast.success("Account imported");
      invalidateAccountRelatedQueries(queryClient);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Import failed");
    },
  });

  const pauseMutation = useMutation({
    mutationFn: pauseAccount,
    onSuccess: () => {
      toast.success("Account paused");
      invalidateAccountRelatedQueries(queryClient);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Pause failed");
    },
  });

  const resumeMutation = useMutation({
    mutationFn: reactivateAccount,
    onSuccess: () => {
      toast.success("Account resumed");
      invalidateAccountRelatedQueries(queryClient);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Resume failed");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteAccount,
    onSuccess: () => {
      toast.success("Account deleted");
      invalidateAccountRelatedQueries(queryClient);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Delete failed");
    },
  });

  const updateConnectionMutation = useMutation({
    mutationFn: ({ accountId, payload }: { accountId: string; payload: { mode: "inherit_default" | "direct" | "proxy_profile"; proxyProfileId?: string | null } }) =>
      updateAccountConnection(accountId, payload),
    onSuccess: () => {
      toast.success("Connection updated");
      invalidateAccountRelatedQueries(queryClient);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Connection update failed");
    },
  });

  const deleteChatGPTImageSessionMutation = useMutation({
    mutationFn: (accountId: string) => deleteAccountChatGPTImageSession(accountId),
    onSuccess: () => {
      toast.success("ChatGPT Images session disconnected");
      invalidateAccountRelatedQueries(queryClient);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to disconnect ChatGPT Images session");
    },
  });

  const updateChatGPTImageCredentialsMutation = useMutation({
    mutationFn: ({ accountId, loginEmail, password }: { accountId: string; loginEmail: string; password: string }) =>
      updateAccountChatGPTImageCredentials(accountId, { loginEmail, password }),
    onSuccess: () => {
      toast.success("ChatGPT Images automation saved");
      invalidateAccountRelatedQueries(queryClient);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to save ChatGPT Images automation");
    },
  });

  const deleteChatGPTImageCredentialsMutation = useMutation({
    mutationFn: (accountId: string) => deleteAccountChatGPTImageCredentials(accountId),
    onSuccess: () => {
      toast.success("ChatGPT Images automation cleared");
      invalidateAccountRelatedQueries(queryClient);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to clear ChatGPT Images automation");
    },
  });

  return {
    importMutation,
    pauseMutation,
    resumeMutation,
    deleteMutation,
    updateConnectionMutation,
    deleteChatGPTImageSessionMutation,
    updateChatGPTImageCredentialsMutation,
    deleteChatGPTImageCredentialsMutation,
  };
}

export function useAccountTrends(accountId: string | null) {
  return useQuery({
    queryKey: ["accounts", "trends", accountId],
    queryFn: () => getAccountTrends(accountId!),
    enabled: !!accountId,
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
    refetchIntervalInBackground: false,
  });
}

export function useAccounts() {
  const accountsQuery = useQuery({
    queryKey: ["accounts", "list"],
    queryFn: listAccounts,
    select: (data) => data.accounts,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });

  const mutations = useAccountMutations();

  return { accountsQuery, ...mutations };
}

export function useChatGPTImageSession(accountId: string | null) {
  return useQuery({
    queryKey: ["accounts", "chatgpt-image-session", accountId],
    queryFn: () => getAccountChatGPTImageSession(accountId!),
    enabled: !!accountId,
    staleTime: 5_000,
    refetchInterval: 5_000,
    refetchIntervalInBackground: false,
  });
}

export function useChatGPTImageCredentials(accountId: string | null) {
  return useQuery({
    queryKey: ["accounts", "chatgpt-image-credentials", accountId],
    queryFn: () => getAccountChatGPTImageCredentials(accountId!),
    enabled: !!accountId,
    staleTime: 5_000,
    refetchInterval: 5_000,
    refetchIntervalInBackground: false,
  });
}
