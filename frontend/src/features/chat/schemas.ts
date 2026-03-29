import { z } from "zod";

export const ChatTextPartSchema = z.object({
  type: z.literal("text"),
  text: z.string(),
});

export const ChatAttachmentSchema = z.object({
  type: z.literal("image"),
  dataUrl: z.string(),
  mimeType: z.enum(["image/png", "image/jpeg", "image/webp"]),
  filename: z.string().min(1),
});

export const ChatContentPartSchema = z.union([ChatTextPartSchema, ChatAttachmentSchema]);

export const ChatMessageSchema = z.object({
  id: z.string(),
  role: z.enum(["user", "assistant", "system"]),
  content: z.array(ChatContentPartSchema).min(1),
  status: z.enum(["done", "streaming", "error", "stopped"]).default("done"),
  errorMessage: z.string().nullable().default(null),
});

export const ChatThreadSchema = z.object({
  id: z.string(),
  title: z.string(),
  createdAt: z.string().datetime({ offset: true }),
  updatedAt: z.string().datetime({ offset: true }),
  model: z.string().nullable().default(null),
  accountId: z.string().nullable().default(null),
  lastResolvedAccountId: z.string().nullable().default(null),
  messages: z.array(ChatMessageSchema).default([]),
});

export const ChatStateSchema = z.object({
  threads: z.array(ChatThreadSchema).default([]),
});

export const DashboardChatRequestSchema = z.object({
  accountId: z.string().nullable().optional(),
  model: z.string().min(1),
  reasoningEffort: z.enum(["low", "medium", "high"]).nullable().optional(),
  messages: z.array(
    z.object({
      role: z.enum(["user", "assistant", "system"]),
      content: z.array(
        z.union([
          z.object({
            type: z.literal("text"),
            text: z.string().min(1),
          }),
          ChatAttachmentSchema,
        ]),
      ).min(1),
    }),
  ).min(1),
});

export const DashboardChatStartedEventSchema = z.object({
  type: z.literal("dashboard.chat.started"),
  mode: z.enum(["auto", "account"]),
  requestedAccountId: z.string().nullable(),
  resolvedAccountId: z.string().nullable(),
});

export type ChatAttachment = z.infer<typeof ChatAttachmentSchema>;
export type ChatContentPart = z.infer<typeof ChatContentPartSchema>;
export type ChatMessage = z.infer<typeof ChatMessageSchema>;
export type ChatThread = z.infer<typeof ChatThreadSchema>;
export type ChatState = z.infer<typeof ChatStateSchema>;
export type DashboardChatRequest = z.infer<typeof DashboardChatRequestSchema>;
export type DashboardChatStartedEvent = z.infer<typeof DashboardChatStartedEventSchema>;

