import { z } from "zod";

export const ProxyProfileSchema = z.object({
  id: z.string(),
  name: z.string(),
  protocol: z.literal("vless"),
  transportKind: z.enum(["reality_tcp", "ws_tls", "tls_tcp"]),
  serverHost: z.string(),
  serverPort: z.number().int(),
  localProxyPort: z.number().int(),
});

export const ProxyProfilesResponseSchema = z.object({
  profiles: z.array(ProxyProfileSchema),
});

export const ProxyProfileStatusSchema = z.object({
  profileId: z.string(),
  status: z.enum(["ok", "error"]),
  egressIp: z.string().nullable().optional(),
  lastError: z.string().nullable().optional(),
  checkedAt: z.string().datetime({ offset: true }),
  latencyMs: z.number().int().nullable().optional(),
});

export const ProxyProfileStatusesResponseSchema = z.object({
  statuses: z.array(ProxyProfileStatusSchema),
});

export const ProxyProfileCreateRequestSchema = z.object({
  name: z.string().min(1),
  vlessUri: z.string().min(1),
});

export const ProxyProfileUpdateRequestSchema = z.object({
  name: z.string().min(1),
  vlessUri: z.string().min(1).optional(),
});

export type ProxyProfile = z.infer<typeof ProxyProfileSchema>;
export type ProxyProfileStatus = z.infer<typeof ProxyProfileStatusSchema>;
export type ProxyProfileCreateRequest = z.infer<typeof ProxyProfileCreateRequestSchema>;
export type ProxyProfileUpdateRequest = z.infer<typeof ProxyProfileUpdateRequestSchema>;
