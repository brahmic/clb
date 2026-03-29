import { useEffect, useMemo, useRef, useState } from "react";
import {
  ImagePlus,
  MessageSquare,
  MessageSquarePlus,
  Paperclip,
  Send,
  Square,
  Sparkles,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { AlertMessage } from "@/components/alert-message";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SpinnerBlock } from "@/components/ui/spinner";
import { useAccounts } from "@/features/accounts/hooks/use-accounts";
import { useModels } from "@/features/api-keys/hooks/use-models";
import { streamDashboardChatResponse } from "@/features/chat/api";
import {
  loadChatPreferences,
  loadChatState,
  saveChatPreferences,
  saveChatState,
} from "@/features/chat/storage";
import type {
  ChatAttachment,
  ChatMessage,
  ChatThread,
  DashboardChatStartedEvent,
  DashboardChatRequest,
} from "@/features/chat/schemas";
import { cn } from "@/lib/utils";

const ACCOUNT_AUTO_VALUE = "__auto__";
const MAX_THREADS = 20;
const MAX_ATTACHMENTS_PER_TURN = 3;
const MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024;
const ALLOWED_IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);

function createId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `chat_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function createThread(params?: { model?: string | null; accountId?: string | null }): ChatThread {
  const now = new Date().toISOString();
  return {
    id: createId(),
    title: "New chat",
    createdAt: now,
    updatedAt: now,
    model: params?.model ?? null,
    accountId: params?.accountId ?? null,
    lastResolvedAccountId: null,
    messages: [],
  };
}

function updateThreadList(
  threads: ChatThread[],
  threadId: string,
  updater: (thread: ChatThread) => ChatThread,
): ChatThread[] {
  const current = threads.find((thread) => thread.id === threadId);
  if (!current) {
    return threads;
  }
  const next = updater(current);
  return [next, ...threads.filter((thread) => thread.id !== threadId)].slice(0, MAX_THREADS);
}

function deriveThreadTitle(messages: ChatMessage[]): string {
  const firstUserText = messages
    .flatMap((message) => (message.role === "user" ? message.content : []))
    .find((part) => part.type === "text" && part.text.trim().length > 0);
  if (!firstUserText || firstUserText.type !== "text") {
    return "New chat";
  }
  return firstUserText.text.trim().slice(0, 48) || "New chat";
}

function getAssistantText(message: ChatMessage): string {
  return message.content
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("");
}

function setAssistantText(message: ChatMessage, text: string, status?: ChatMessage["status"]): ChatMessage {
  const nextContent = message.content.some((part) => part.type === "text")
    ? message.content.map((part) => (part.type === "text" ? { ...part, text } : part))
    : [{ type: "text" as const, text }];
  return {
    ...message,
    content: nextContent,
    status: status ?? message.status,
  };
}

function appendAssistantDelta(message: ChatMessage, delta: string): ChatMessage {
  const nextText = getAssistantText(message) + delta;
  return setAssistantText(message, nextText, "streaming");
}

function toRequestMessages(messages: ChatMessage[]): DashboardChatRequest["messages"] {
  return messages
    .map((message) => ({
      role: message.role,
      content: message.content.filter((part) => part.type === "image" || part.text.trim().length > 0),
    }))
    .filter((message) => message.content.length > 0);
}

function formatThreadLabel(thread: ChatThread): string {
  const suffix = thread.messages.length > 0 ? ` · ${thread.messages.length} msg` : "";
  return `${thread.title}${suffix}`;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) {
    return `${Math.round(bytes / 102.4) / 10} KB`;
  }
  return `${Math.round(bytes / (1024 * 1024) * 10) / 10} MB`;
}

function normalizeAccountPreference(value: string | null): string | null {
  if (value === null || value === ACCOUNT_AUTO_VALUE) {
    return null;
  }
  return value;
}

async function readFileAsDataUrl(file: File): Promise<string> {
  return await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(typeof reader.result === "string" ? reader.result : "");
    reader.onerror = () => reject(reader.error ?? new Error("Failed to read image"));
    reader.readAsDataURL(file);
  });
}

function renderLinkedText(text: string) {
  const parts = text.split(/(https?:\/\/[^\s]+)/g);
  return parts.map((part, index) => {
    if (/^https?:\/\/[^\s]+$/.test(part)) {
      return (
        <a
          key={`${part}-${index}`}
          href={part}
          target="_blank"
          rel="noreferrer"
          className="text-primary underline underline-offset-2"
        >
          {part}
        </a>
      );
    }
    return <span key={`${index}-${part}`}>{part}</span>;
  });
}

function extractStreamErrorMessage(event: Record<string, unknown>): string {
  if (event.type === "response.failed") {
    const response = event.response;
    if (response && typeof response === "object" && "error" in response) {
      const error = response.error;
      if (error && typeof error === "object" && "message" in error && typeof error.message === "string") {
        return error.message;
      }
    }
  }
  if ("error" in event && event.error && typeof event.error === "object" && "message" in event.error) {
    const message = event.error.message;
    if (typeof message === "string") {
      return message;
    }
  }
  return "Request failed";
}

function isStartedEvent(event: Record<string, unknown>): event is DashboardChatStartedEvent {
  return (
    event.type === "dashboard.chat.started" &&
    ("resolvedAccountId" in event ? event.resolvedAccountId === null || typeof event.resolvedAccountId === "string" : true)
  );
}

function isTextDeltaEvent(event: Record<string, unknown>): event is { type: "response.output_text.delta"; delta: string } {
  return event.type === "response.output_text.delta" && typeof event.delta === "string";
}

function isTextDoneEvent(event: Record<string, unknown>): event is { type: "response.output_text.done"; text: string } {
  return event.type === "response.output_text.done" && typeof event.text === "string";
}

export function ChatPage() {
  const { accountsQuery } = useAccounts();
  const modelsQuery = useModels();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const [storageReady, setStorageReady] = useState(false);
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);

  const accounts = accountsQuery.data ?? [];
  const activeAccounts = accounts.filter((account) => account.status === "active");
  const models = modelsQuery.data ?? [];

  const activeThread = useMemo(
    () => threads.find((thread) => thread.id === activeThreadId) ?? threads[0] ?? null,
    [activeThreadId, threads],
  );

  const selectedModel = activeThread?.model ?? models[0]?.id ?? "";
  const selectedAccountValue = activeThread?.accountId ?? ACCOUNT_AUTO_VALUE;

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      const storedState = await loadChatState();
      const preferences = loadChatPreferences();
      if (cancelled) {
        return;
      }
      const initialThreads =
        storedState.threads.length > 0
          ? storedState.threads.slice(0, MAX_THREADS)
          : [createThread({ model: preferences.lastModel, accountId: normalizeAccountPreference(preferences.lastAccount) })];
      setThreads(initialThreads);
      setActiveThreadId(
        preferences.activeThreadId && initialThreads.some((thread) => thread.id === preferences.activeThreadId)
          ? preferences.activeThreadId
          : initialThreads[0]?.id ?? null,
      );
      setStorageReady(true);
    })();

    return () => {
      cancelled = true;
      abortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (!storageReady) {
      return;
    }
    void saveChatState({ threads: threads.slice(0, MAX_THREADS) });
    saveChatPreferences({
      activeThreadId,
      lastModel: selectedModel || null,
      lastAccount: selectedAccountValue,
    });
  }, [activeThreadId, selectedAccountValue, selectedModel, storageReady, threads]);

  useEffect(() => {
    const element = textareaRef.current;
    if (!element) {
      return;
    }
    element.style.height = "0px";
    element.style.height = `${Math.min(element.scrollHeight, 220)}px`;
  }, [draft]);

  const resolvedAccountLabel = useMemo(() => {
    if (!activeThread?.lastResolvedAccountId) {
      return null;
    }
    const matched = accounts.find((account) => account.accountId === activeThread.lastResolvedAccountId);
    return matched?.displayName || matched?.email || activeThread.lastResolvedAccountId;
  }, [accounts, activeThread?.lastResolvedAccountId]);

  const queryError =
    (accountsQuery.error instanceof Error && accountsQuery.error.message) ||
    (modelsQuery.error instanceof Error && modelsQuery.error.message) ||
    null;

  const canSend = (draft.trim().length > 0 || attachments.length > 0) && selectedModel.length > 0 && !streaming;

  const handleSelectThread = (threadId: string) => {
    if (streaming) {
      return;
    }
    setActiveThreadId(threadId);
    setDraft("");
    setAttachments([]);
    setPageError(null);
  };

  const handleNewChat = () => {
    if (streaming) {
      return;
    }
    const nextThread = createThread({
      model: selectedModel || null,
      accountId: normalizeAccountPreference(selectedAccountValue),
    });
    setThreads((current) => [nextThread, ...current].slice(0, MAX_THREADS));
    setActiveThreadId(nextThread.id);
    setDraft("");
    setAttachments([]);
    setPageError(null);
  };

  const updateActiveThread = (updater: (thread: ChatThread) => ChatThread) => {
    if (!activeThread) {
      return;
    }
    setThreads((current) => updateThreadList(current, activeThread.id, updater));
  };

  const handleModelChange = (value: string) => {
    updateActiveThread((thread) => ({
      ...thread,
      model: value,
      updatedAt: new Date().toISOString(),
    }));
  };

  const handleAccountChange = (value: string) => {
    updateActiveThread((thread) => ({
      ...thread,
      accountId: normalizeAccountPreference(value),
      lastResolvedAccountId: null,
      updatedAt: new Date().toISOString(),
    }));
  };

  const handleAttachmentSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (selectedFiles.length === 0) {
      return;
    }
    if (attachments.length + selectedFiles.length > MAX_ATTACHMENTS_PER_TURN) {
      toast.error(`Attach up to ${MAX_ATTACHMENTS_PER_TURN} images per message`);
      return;
    }

    const nextAttachments: ChatAttachment[] = [];
    for (const file of selectedFiles) {
      if (!ALLOWED_IMAGE_TYPES.has(file.type)) {
        toast.error(`${file.name}: unsupported image type`);
        continue;
      }
      if (file.size > MAX_IMAGE_SIZE_BYTES) {
        toast.error(`${file.name}: file is larger than ${formatBytes(MAX_IMAGE_SIZE_BYTES)}`);
        continue;
      }
      const dataUrl = await readFileAsDataUrl(file);
      nextAttachments.push({
        type: "image",
        dataUrl,
        mimeType: file.type as ChatAttachment["mimeType"],
        filename: file.name,
      });
    }
    if (nextAttachments.length > 0) {
      setAttachments((current) => [...current, ...nextAttachments].slice(0, MAX_ATTACHMENTS_PER_TURN));
    }
  };

  const removeAttachment = (filename: string) => {
    setAttachments((current) => current.filter((attachment) => attachment.filename !== filename));
  };

  const handleStop = () => {
    abortRef.current?.abort();
  };

  const handleSend = async () => {
    if (!activeThread || !canSend) {
      return;
    }

    const text = draft.trim();
    const userMessage: ChatMessage = {
      id: createId(),
      role: "user",
      content: [
        ...(text.length > 0 ? [{ type: "text" as const, text }] : []),
        ...attachments,
      ],
      status: "done",
      errorMessage: null,
    };
    const assistantMessageId = createId();
    const assistantMessage: ChatMessage = {
      id: assistantMessageId,
      role: "assistant",
      content: [{ type: "text", text: "" }],
      status: "streaming",
      errorMessage: null,
    };
    const nextUpdatedAt = new Date().toISOString();
    const nextMessages = [...activeThread.messages, userMessage, assistantMessage];
    const nextThread: ChatThread = {
      ...activeThread,
      title: deriveThreadTitle(nextMessages),
      updatedAt: nextUpdatedAt,
      lastResolvedAccountId: null,
      messages: nextMessages,
    };

    setThreads((current) => updateThreadList(current, activeThread.id, () => nextThread));
    setDraft("");
    setAttachments([]);
    setPageError(null);
    setStreaming(true);

    const abortController = new AbortController();
    abortRef.current = abortController;

    try {
      await streamDashboardChatResponse(
        {
          accountId: nextThread.accountId,
          model: selectedModel,
          messages: toRequestMessages(nextThread.messages.filter((message) => message.id !== assistantMessageId)),
        },
        {
          signal: abortController.signal,
          onEvent: (event) => {
            const eventRecord = event as Record<string, unknown>;
            if (!activeThread) {
              return;
            }
            if (isStartedEvent(eventRecord)) {
              setThreads((current) =>
                updateThreadList(current, activeThread.id, (thread) => ({
                  ...thread,
                  lastResolvedAccountId: eventRecord.resolvedAccountId,
                  updatedAt: new Date().toISOString(),
                })),
              );
              return;
            }
            if (isTextDeltaEvent(eventRecord)) {
              setThreads((current) =>
                updateThreadList(current, activeThread.id, (thread) => ({
                  ...thread,
                  updatedAt: new Date().toISOString(),
                  messages: thread.messages.map((message) =>
                    message.id === assistantMessageId ? appendAssistantDelta(message, eventRecord.delta) : message,
                  ),
                })),
              );
              return;
            }
            if (isTextDoneEvent(eventRecord)) {
              setThreads((current) =>
                updateThreadList(current, activeThread.id, (thread) => ({
                  ...thread,
                  updatedAt: new Date().toISOString(),
                  messages: thread.messages.map((message) =>
                    message.id === assistantMessageId
                      ? setAssistantText(message, eventRecord.text, "streaming")
                      : message,
                  ),
                })),
              );
              return;
            }
            if (eventRecord.type === "response.completed") {
              setThreads((current) =>
                updateThreadList(current, activeThread.id, (thread) => ({
                  ...thread,
                  updatedAt: new Date().toISOString(),
                  messages: thread.messages.map((message) =>
                    message.id === assistantMessageId ? { ...message, status: "done" } : message,
                  ),
                })),
              );
              return;
            }
            if (eventRecord.type === "response.failed" || eventRecord.type === "error") {
              const errorMessage = extractStreamErrorMessage(eventRecord);
              setThreads((current) =>
                updateThreadList(current, activeThread.id, (thread) => ({
                  ...thread,
                  updatedAt: new Date().toISOString(),
                  messages: thread.messages.map((message) =>
                    message.id === assistantMessageId
                      ? {
                          ...setAssistantText(message, getAssistantText(message), "error"),
                          errorMessage,
                        }
                      : message,
                  ),
                })),
              );
              setPageError(errorMessage);
            }
          },
        },
      );
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        setThreads((current) =>
          updateThreadList(current, activeThread.id, (thread) => ({
            ...thread,
            updatedAt: new Date().toISOString(),
            messages: thread.messages.map((message) =>
              message.id === assistantMessageId ? { ...message, status: "stopped" } : message,
            ),
          })),
        );
      } else {
        const message = error instanceof Error ? error.message : "Chat request failed";
        setThreads((current) =>
          updateThreadList(current, activeThread.id, (thread) => ({
            ...thread,
            updatedAt: new Date().toISOString(),
            messages: thread.messages.map((item) =>
              item.id === assistantMessageId
                ? {
                    ...setAssistantText(item, getAssistantText(item), "error"),
                    errorMessage: message,
                  }
                : item,
            ),
          })),
        );
        setPageError(message);
      }
    } finally {
      abortRef.current = null;
      setStreaming(false);
    }
  };

  if (!storageReady || activeThread === null) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <SpinnerBlock label="Loading chat workspace..." />
      </div>
    );
  }

  return (
    <div className="animate-fade-in-up space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <MessageSquare className="h-5 w-5 text-primary" />
            Chat
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Operator chat with account pinning, auto-routing, and image input.
          </p>
        </div>
        {resolvedAccountLabel ? (
          <Badge variant="outline" className="gap-1.5">
            <Sparkles className="h-3 w-3" />
            Served by {resolvedAccountLabel}
          </Badge>
        ) : null}
      </div>

      {queryError ? <AlertMessage variant="error">{queryError}</AlertMessage> : null}
      {pageError ? <AlertMessage variant="error">{pageError}</AlertMessage> : null}

      <section className="overflow-hidden rounded-[1.4rem] border border-border/70 bg-card/80 shadow-sm">
        <div className="border-b border-border/60 bg-muted/25 px-4 py-4 sm:px-5">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-1 flex-col gap-3 sm:flex-row">
              <Select value={activeThread.id} onValueChange={handleSelectThread} disabled={streaming}>
                <SelectTrigger className="w-full min-w-0 sm:max-w-[20rem]">
                  <SelectValue placeholder="Select thread" />
                </SelectTrigger>
                <SelectContent>
                  {threads.map((thread) => (
                    <SelectItem key={thread.id} value={thread.id}>
                      {formatThreadLabel(thread)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <Select value={selectedModel} onValueChange={handleModelChange} disabled={streaming || models.length === 0}>
                <SelectTrigger className="w-full sm:max-w-[14rem]">
                  <SelectValue placeholder="Select model" />
                </SelectTrigger>
                <SelectContent>
                  {models.map((model) => (
                    <SelectItem key={model.id} value={model.id}>
                      {model.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <Select value={selectedAccountValue} onValueChange={handleAccountChange} disabled={streaming}>
                <SelectTrigger className="w-full sm:max-w-[16rem]">
                  <SelectValue placeholder="Routing mode" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ACCOUNT_AUTO_VALUE}>Auto routing</SelectItem>
                  {activeAccounts.map((account) => (
                    <SelectItem key={account.accountId} value={account.accountId}>
                      {account.displayName || account.email || account.accountId}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <Button type="button" variant="outline" size="sm" onClick={handleNewChat} disabled={streaming}>
              <MessageSquarePlus className="h-3.5 w-3.5" />
              New chat
            </Button>
          </div>
        </div>

        <div className="flex min-h-[60vh] flex-col">
          <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-5">
            {activeThread.messages.length === 0 ? (
              <div className="flex h-full min-h-[22rem] items-center justify-center">
                <div className="max-w-md rounded-2xl border border-dashed border-border/80 bg-background/80 px-6 py-8 text-center">
                  <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                    <ImagePlus className="h-5 w-5" />
                  </div>
                  <p className="text-sm font-medium">Start a new operator chat</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Pick `Auto` to use the normal load balancer, or pin a specific active account for a single thread.
                  </p>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                {activeThread.messages.map((message) => {
                  const isUser = message.role === "user";
                  return (
                    <div key={message.id} className={cn("flex", isUser ? "justify-end" : "justify-start")}>
                      <div
                        className={cn(
                          "max-w-[88%] rounded-2xl border px-4 py-3 shadow-xs sm:max-w-[80%]",
                          isUser
                            ? "border-primary/20 bg-primary/8 text-foreground"
                            : "border-border/70 bg-background text-foreground",
                        )}
                      >
                        <div className="mb-2 flex items-center gap-2">
                          <Badge variant={isUser ? "default" : "outline"}>{isUser ? "You" : "Assistant"}</Badge>
                          {message.status === "streaming" ? <Badge variant="outline">Streaming</Badge> : null}
                          {message.status === "stopped" ? <Badge variant="outline">Stopped</Badge> : null}
                          {message.status === "error" ? <Badge variant="destructive">Error</Badge> : null}
                        </div>

                        <div className="space-y-3">
                          {message.content.map((part, index) =>
                            part.type === "text" ? (
                              part.text.length > 0 ? (
                                <p key={`${message.id}-text-${index}`} className="whitespace-pre-wrap break-words text-sm leading-6">
                                  {renderLinkedText(part.text)}
                                </p>
                              ) : null
                            ) : (
                              <div
                                key={`${message.id}-image-${index}`}
                                className="overflow-hidden rounded-xl border border-border/70 bg-muted/30"
                              >
                                <img src={part.dataUrl} alt={part.filename} className="max-h-72 w-full object-cover" />
                                <div className="border-t border-border/70 px-3 py-2 text-xs text-muted-foreground">
                                  {part.filename}
                                </div>
                              </div>
                            ),
                          )}
                        </div>

                        {message.errorMessage ? (
                          <p className="mt-3 rounded-lg bg-destructive/8 px-3 py-2 text-xs text-destructive">
                            {message.errorMessage}
                          </p>
                        ) : null}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div className="border-t border-border/70 bg-background/80 px-4 py-4 sm:px-5">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              multiple
              hidden
              onChange={handleAttachmentSelect}
            />

            {attachments.length > 0 ? (
              <div className="mb-3 flex flex-wrap gap-2">
                {attachments.map((attachment) => (
                  <div
                    key={attachment.filename}
                    className="flex items-center gap-2 rounded-full border border-border/70 bg-muted/40 px-3 py-1.5 text-xs"
                  >
                    <img src={attachment.dataUrl} alt={attachment.filename} className="h-6 w-6 rounded-full object-cover" />
                    <span className="max-w-32 truncate">{attachment.filename}</span>
                    <button
                      type="button"
                      className="text-muted-foreground transition-colors hover:text-foreground"
                      onClick={() => removeAttachment(attachment.filename)}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            ) : null}

            <div className="rounded-[1.35rem] border border-border/70 bg-card shadow-xs">
              <textarea
                ref={textareaRef}
                value={draft}
                rows={1}
                placeholder="Message the load balancer through a model..."
                disabled={streaming}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void handleSend();
                  }
                }}
                className="max-h-[220px] min-h-[56px] w-full resize-none bg-transparent px-4 py-3 text-sm outline-none"
              />

              <div className="flex flex-col gap-3 border-t border-border/70 px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 rounded-full border border-border/70 px-3 py-1.5 transition-colors hover:bg-muted"
                    disabled={streaming}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <Paperclip className="h-3.5 w-3.5" />
                    Attach image
                  </button>
                  <span>PNG, JPEG, WebP up to 5 MB each</span>
                </div>

                <div className="flex items-center justify-end gap-2">
                  {streaming ? (
                    <Button type="button" variant="outline" size="sm" onClick={handleStop}>
                      <Square className="h-3.5 w-3.5" />
                      Stop
                    </Button>
                  ) : null}
                  <Button type="button" size="sm" onClick={() => void handleSend()} disabled={!canSend}>
                    <Send className="h-3.5 w-3.5" />
                    Send
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
