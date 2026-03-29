import { ApiError } from "@/lib/api-client";
import { ApiErrorResponseSchema } from "@/schemas/api";

import {
  DashboardChatRequestSchema,
  DashboardChatStartedEventSchema,
  type DashboardChatRequest,
  type DashboardChatStartedEvent,
} from "@/features/chat/schemas";

type UnknownChatEvent = Record<string, unknown>;
export type DashboardChatEvent = DashboardChatStartedEvent | UnknownChatEvent;

type StreamDashboardChatOptions = {
  signal?: AbortSignal;
  onEvent: (event: DashboardChatEvent) => void;
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

function parseSseBlock(block: string): DashboardChatEvent | null {
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
  const parsed = JSON.parse(raw) as Record<string, unknown>;
  const started = DashboardChatStartedEventSchema.safeParse(parsed);
  return started.success ? started.data : parsed;
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

export async function streamDashboardChatResponse(
  payload: DashboardChatRequest,
  options: StreamDashboardChatOptions,
): Promise<void> {
  const validated = DashboardChatRequestSchema.parse(payload);
  const response = await fetch("/api/dashboard-chat/responses", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    credentials: "same-origin",
    body: JSON.stringify(validated),
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
      const event = parseSseBlock(block);
      if (event !== null) {
        options.onEvent(event);
      }
    }
    if (done) {
      break;
    }
  }

  if (buffer.trim().length > 0) {
    const finalEvent = parseSseBlock(buffer);
    if (finalEvent !== null) {
      options.onEvent(finalEvent);
    }
  }
}
