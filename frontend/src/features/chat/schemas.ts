import { z } from "zod";

export const ChatTextPartSchema = z.object({
  type: z.literal("text"),
  text: z.string(),
});

export const ChatThreadModeSchema = z.enum(["chat", "chatgpt_images"]);

export const GeneratedAssetMetadataSchema = z.object({
  fileId: z.string().min(1),
  originalGenId: z.string().nullable().default(null),
});

export const ChatAttachmentSchema = z.object({
  type: z.literal("image"),
  dataUrl: z.string(),
  mimeType: z.enum(["image/png", "image/jpeg", "image/webp"]),
  filename: z.string().min(1),
  source: z.enum(["upload", "generated"]).default("upload"),
  revisedPrompt: z.string().nullable().default(null),
  generatedAsset: GeneratedAssetMetadataSchema.nullable().default(null),
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
  mode: ChatThreadModeSchema.default("chat"),
  conversationId: z.string().nullable().default(null),
  parentMessageId: z.string().nullable().default(null),
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
          z.object({
            type: z.literal("image"),
            dataUrl: z.string(),
            mimeType: z.enum(["image/png", "image/jpeg", "image/webp"]),
            filename: z.string().min(1),
          }),
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

export const DashboardImagesConversationRequestSchema = z.object({
  accountId: z.string().nullable().optional(),
  model: z.string().min(1),
  conversationId: z.string().nullable().optional(),
  parentMessageId: z.string().nullable().optional(),
  timezoneOffsetMin: z.number().int(),
  timezone: z.string().min(1),
  clientContext: z.record(z.string(), z.union([z.string(), z.number(), z.boolean(), z.null()])).default({}),
  prompt: z.string().min(1),
  attachments: z.array(
    z.object({
      dataUrl: z.string(),
      mimeType: z.enum(["image/png", "image/jpeg", "image/webp"]),
      filename: z.string().min(1),
    }),
  ).max(3).default([]),
  editTarget: GeneratedAssetMetadataSchema.nullable().optional(),
});

export const DashboardImagesStartedEventSchema = z.object({
  type: z.literal("dashboard.images.started"),
  mode: z.enum(["auto", "account"]),
  requestedAccountId: z.string().nullable(),
  resolvedAccountId: z.string().nullable(),
});

export const DashboardImagesProgressEventSchema = z.object({
  type: z.literal("dashboard.images.progress"),
  phase: z.string(),
  message: z.string().nullable().optional(),
});

export const DashboardGeneratedImageSchema = z.object({
  dataUrl: z.string(),
  mimeType: z.enum(["image/png", "image/jpeg", "image/webp"]),
  filename: z.string().min(1),
  fileId: z.string().min(1),
  originalGenId: z.string().nullable().default(null),
  revisedPrompt: z.string().nullable().default(null),
});

export const DashboardImagesCompletedEventSchema = z.object({
  type: z.literal("dashboard.images.completed"),
  conversationId: z.string().min(1),
  assistantMessageId: z.string().min(1),
  parentMessageId: z.string().min(1),
  assistantText: z.string().nullable().optional(),
  images: z.array(DashboardGeneratedImageSchema).min(1),
});

export const DashboardImagesFailedEventSchema = z.object({
  type: z.literal("dashboard.images.failed"),
  code: z.string().min(1),
  message: z.string().min(1),
});

export type ChatAttachment = z.infer<typeof ChatAttachmentSchema>;
export type ChatContentPart = z.infer<typeof ChatContentPartSchema>;
export type ChatMessage = z.infer<typeof ChatMessageSchema>;
export type ChatThread = z.infer<typeof ChatThreadSchema>;
export type ChatState = z.infer<typeof ChatStateSchema>;
export type GeneratedAssetMetadata = z.infer<typeof GeneratedAssetMetadataSchema>;
export type DashboardChatRequest = z.infer<typeof DashboardChatRequestSchema>;
export type DashboardChatStartedEvent = z.infer<typeof DashboardChatStartedEventSchema>;
export type DashboardImagesConversationRequest = z.infer<typeof DashboardImagesConversationRequestSchema>;
export type DashboardImagesStartedEvent = z.infer<typeof DashboardImagesStartedEventSchema>;
export type DashboardImagesProgressEvent = z.infer<typeof DashboardImagesProgressEventSchema>;
export type DashboardGeneratedImage = z.infer<typeof DashboardGeneratedImageSchema>;
export type DashboardImagesCompletedEvent = z.infer<typeof DashboardImagesCompletedEventSchema>;
export type DashboardImagesFailedEvent = z.infer<typeof DashboardImagesFailedEventSchema>;
export type ChatThreadMode = z.infer<typeof ChatThreadModeSchema>;
