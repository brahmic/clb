import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  createProxyProfile,
  deleteProxyProfile,
  listProxyProfiles,
  listProxyProfileStatuses,
  updateProxyProfile,
} from "@/features/proxy-profiles/api";
import type { ProxyProfileUpdateRequest } from "@/features/proxy-profiles/schemas";

function invalidateProxyRelatedQueries(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: ["proxy-profiles", "list"] });
  void queryClient.invalidateQueries({ queryKey: ["proxy-profiles", "statuses"] });
  void queryClient.invalidateQueries({ queryKey: ["settings", "detail"] });
  void queryClient.invalidateQueries({ queryKey: ["accounts", "list"] });
  void queryClient.invalidateQueries({ queryKey: ["dashboard", "overview"] });
}

export function useProxyProfiles(options?: { includeStatuses?: boolean }) {
  const queryClient = useQueryClient();
  const includeStatuses = options?.includeStatuses ?? false;

  const profilesQuery = useQuery({
    queryKey: ["proxy-profiles", "list"],
    queryFn: listProxyProfiles,
    select: (data) => data.profiles,
  });

  const statusesQuery = useQuery({
    queryKey: ["proxy-profiles", "statuses"],
    queryFn: listProxyProfileStatuses,
    select: (data) => data.statuses,
    refetchInterval: 30_000,
    enabled: includeStatuses && (profilesQuery.data?.length ?? 0) > 0,
  });

  const createMutation = useMutation({
    mutationFn: createProxyProfile,
    onSuccess: () => {
      toast.success("Proxy profile created");
      invalidateProxyRelatedQueries(queryClient);
    },
    onError: (error: Error) => toast.error(error.message || "Failed to create proxy profile"),
  });

  const updateMutation = useMutation({
    mutationFn: ({ profileId, payload }: { profileId: string; payload: ProxyProfileUpdateRequest }) =>
      updateProxyProfile(profileId, payload),
    onSuccess: () => {
      toast.success("Proxy profile updated");
      invalidateProxyRelatedQueries(queryClient);
    },
    onError: (error: Error) => toast.error(error.message || "Failed to update proxy profile"),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteProxyProfile,
    onSuccess: () => {
      toast.success("Proxy profile deleted");
      invalidateProxyRelatedQueries(queryClient);
    },
    onError: (error: Error) => toast.error(error.message || "Failed to delete proxy profile"),
  });

  return { profilesQuery, statusesQuery, createMutation, updateMutation, deleteMutation };
}
