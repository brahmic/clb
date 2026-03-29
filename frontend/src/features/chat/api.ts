import { ApiError } from "@/lib/api-client";
import { ApiErrorResponseSchema } from "@/schemas/api";

import {
  DashboardChatRequestSchema,
  DashboardChatStartedEventSchema,
  DashboardImagesCompletedEventSchema,
  DashboardImagesConversationRequestSchema,
  DashboardImagesFailedEventSchema,
  DashboardImagesProgressEventSchema,
  DashboardImagesStartedEventSchema,
  type DashboardChatRequest,
  type DashboardChatStartedEvent,
  type DashboardImagesCompletedEvent,
  type DashboardImagesConversationRequest,
  type DashboardImagesFailedEvent,
  type DashboardImagesProgressEvent,
  type DashboardImagesStartedEvent,
} from "@/features/chat/schemas";

type UnknownChatEvent = Record<string, unknown>;

export type DashboardChatEvent = DashboardChatStartedEvent | UnknownChatEvent;
export type DashboardImagesEvent =
  | DashboardImagesStartedEvent
  | DashboardImagesProgressEvent
  | DashboardImagesCompletedEvent
  | DashboardImagesFailedEvent
  | UnknownChatEvent;

type StreamOptions<TEvent> = {
  signal?: AbortSignal;
  onEvent: (event: TEvent) => void;
};

function parseSseBlocks(buffer: string): { blocks: string[]; remainder: string } {
  const blocks: string[] = [];
  let remaining = buffer;
  while (true) {
    const separatorIndex = remaining.indexOf("\n\n");
    if (separatorIndex === -1) {
      break;
    }
    blocks.push(remaining.slice(0, separatorIndex));
    remaining = remaining.slice(separatorIndex + 2);
  }
  return { blocks, remainder: remaining };
}

function parseSseBlock<TEvent>(
  block: string,
  parser: (payload: Record<string, unknown>) => TEvent,
): TEvent | null {
  const dataLines = block
    .split("\n")
    .filter((line) => line.startsWith("data: "))
    .map((line) => line.slice(6));
  if (dataLines.length === 0) {
    return null;
  }
  const raw = dataLines.join("\n");
  if (!raw.trim() || raw.trim() === "[DONE]") {
    return null;
  }
  return parser(JSON.parse(raw) as Record<string, unknown>);
}

async function parseErrorResponse(response: Response): Promise<ApiError> {
  let payload: unknown = undefined;
  try {
    payload = await response.json();
  } catch {
    payload = undefined;
  }
  const parsed = ApiErrorResponseSchema.safeParse(payload);
  if (parsed.success && "error" in parsed.data) {
    const error = parsed.data.error;
    return new ApiError({
      status: response.status,
      code: typeof error.code === "string" ? error.code : "request_failed",
      message:
        typeof error.message === "string" && error.message.length > 0
          ? error.message
          : "Request failed",
      details: error,
      payload,
    });
  }
  return new ApiError({
    status: response.status,
    code: "request_failed",
    message: "Request failed",
    payload,
  });
}

async function streamSse<TRequest, TEvent>(
  url: string,
  payload: TRequest,
  options: StreamOptions<TEvent>,
  parser: (payload: Record<string, unknown>) => TEvent,
): Promise<void> {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    credentials: "same-origin",
    body: JSON.stringify(payload),
    signal: options.signal,
  });
  if (!response.ok) {
    throw await parseErrorResponse(response);
  }
  if (response.body === null) {
    throw new ApiError({
      status: response.status,
      code: "empty_stream",
      message: "Response stream was empty",
    });
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    const { blocks, remainder } = parseSseBlocks(buffer);
    buffer = remainder;
    for (const block of blocks) {
      const event = parseSseBlock(block, parser);
      if (event !== null) {
        options.onEvent(event);
      }
    }
    if (done) {
      break;
    }
  }

  if (buffer.trim().length > 0) {
    const finalEvent = parseSseBlock(buffer, parser);
    if (finalEvent !== null) {
      options.onEvent(finalEvent);
    }
  }
}

function parseDashboardChatEvent(payload: Record<string, unknown>): DashboardChatEvent {
  const started = DashboardChatStartedEventSchema.safeParse(payload);
  return started.success ? started.data : payload;
}

function parseDashboardImagesEvent(payload: Record<string, unknown>): DashboardImagesEvent {
  const started = DashboardImagesStartedEventSchema.safeParse(payload);
  if (started.success) {
    return started.data;
  }
  const progress = DashboardImagesProgressEventSchema.safeParse(payload);
  if (progress.success) {
    return progress.data;
  }
  const completed = DashboardImagesCompletedEventSchema.safeParse(payload);
  if (completed.success) {
    return completed.data;
  }
  const failed = DashboardImagesFailedEventSchema.safeParse(payload);
  return failed.success ? failed.data : payload;
}

export async function streamDashboardChatResponse(
  payload: DashboardChatRequest,
  options: StreamOptions<DashboardChatEvent>,
): Promise<void> {
  const validated = DashboardChatRequestSchema.parse(payload);
  await streamSse("/api/dashboard-chat/responses", validated, options, parseDashboardChatEvent);
}

export async function streamDashboardImageConversation(
  payload: DashboardImagesConversationRequest,
  options: StreamOptions<DashboardImagesEvent>,
): Promise<void> {
  const validated = DashboardImagesConversationRequestSchema.parse(payload);
  await streamSse("/api/dashboard-images/conversation", validated, options, parseDashboardImagesEvent);
}
