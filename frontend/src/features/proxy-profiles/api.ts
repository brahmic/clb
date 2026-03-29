import { del, get, post, put } from "@/lib/api-client";
import {
  ProxyProfileCreateRequestSchema,
  ProxyProfileSchema,
  ProxyProfilesResponseSchema,
  ProxyProfileStatusesResponseSchema,
  ProxyProfileUpdateRequestSchema,
  type ProxyProfileCreateRequest,
  type ProxyProfileUpdateRequest,
} from "@/features/proxy-profiles/schemas";

const PROXY_PROFILES_PATH = "/api/proxy-profiles";

export function listProxyProfiles() {
  return get(PROXY_PROFILES_PATH, ProxyProfilesResponseSchema);
}

export function listProxyProfileStatuses() {
  return get(`${PROXY_PROFILES_PATH}/statuses`, ProxyProfileStatusesResponseSchema);
}

export function createProxyProfile(payload: ProxyProfileCreateRequest) {
  const validated = ProxyProfileCreateRequestSchema.parse(payload);
  return post(PROXY_PROFILES_PATH, ProxyProfileSchema, { body: validated });
}

export function updateProxyProfile(profileId: string, payload: ProxyProfileUpdateRequest) {
  const validated = ProxyProfileUpdateRequestSchema.parse(payload);
  return put(`${PROXY_PROFILES_PATH}/${encodeURIComponent(profileId)}`, ProxyProfileSchema, { body: validated });
}

export function deleteProxyProfile(profileId: string) {
  return del(`${PROXY_PROFILES_PATH}/${encodeURIComponent(profileId)}`, ProxyProfileSchema);
}
