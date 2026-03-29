import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatPage } from "@/features/chat/components/chat-page";
import { renderWithProviders } from "@/test/utils";

const {
  streamDashboardChatResponse,
  streamDashboardImageConversation,
  loadChatState,
  saveChatState,
  loadChatPreferences,
  saveChatPreferences,
  useAccounts,
  useModels,
} = vi.hoisted(() => ({
  streamDashboardChatResponse: vi.fn(),
  streamDashboardImageConversation: vi.fn(),
  loadChatState: vi.fn(),
  saveChatState: vi.fn(),
  loadChatPreferences: vi.fn(),
  saveChatPreferences: vi.fn(),
  useAccounts: vi.fn(),
  useModels: vi.fn(),
}));

vi.mock("@/features/chat/api", () => ({
  streamDashboardChatResponse,
  streamDashboardImageConversation,
}));

vi.mock("@/features/chat/storage", () => ({
  loadChatState,
  saveChatState,
  loadChatPreferences,
  saveChatPreferences,
}));

vi.mock("@/features/accounts/hooks/use-accounts", () => ({
  useAccounts,
}));

vi.mock("@/features/api-keys/hooks/use-models", () => ({
  useModels,
}));

describe("ChatPage", () => {
  beforeEach(() => {
    if (!HTMLElement.prototype.hasPointerCapture) {
      HTMLElement.prototype.hasPointerCapture = () => false;
    }
    if (!HTMLElement.prototype.setPointerCapture) {
      HTMLElement.prototype.setPointerCapture = () => {};
    }
    if (!HTMLElement.prototype.releasePointerCapture) {
      HTMLElement.prototype.releasePointerCapture = () => {};
    }
    if (!HTMLElement.prototype.scrollIntoView) {
      HTMLElement.prototype.scrollIntoView = () => {};
    }
    streamDashboardChatResponse.mockReset();
    streamDashboardImageConversation.mockReset();
    loadChatState.mockResolvedValue({ threads: [] });
    saveChatState.mockResolvedValue(undefined);
    loadChatPreferences.mockReturnValue({
      activeThreadId: null,
      lastModel: null,
      lastAccount: null,
      lastThreadMode: null,
    });
    saveChatPreferences.mockReturnValue(undefined);
    useAccounts.mockReturnValue({
      accountsQuery: {
        data: [
          {
            accountId: "acc_active",
            email: "active@example.com",
            displayName: "Active Account",
            planType: "plus",
            status: "active",
            chatgptImageSession: {
              status: "ready",
              lastValidatedAt: "2026-03-29T09:00:00.000Z",
              lastError: null,
            },
          },
          {
            accountId: "acc_paused",
            email: "paused@example.com",
            displayName: "Paused Account",
            planType: "plus",
            status: "paused",
            chatgptImageSession: {
              status: "disconnected",
              lastValidatedAt: null,
              lastError: null,
            },
          },
        ],
        error: null,
      },
    });
    useModels.mockReturnValue({
      data: [
        { id: "gpt-5.3", name: "GPT 5.3" },
        { id: "gpt-5.1", name: "GPT 5.1" },
      ],
      error: null,
    });
  });

  it("shows auto routing plus active accounts only in the selector", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ChatPage />);

    await screen.findByText("Start a new operator thread");

    const routingButton = screen.getAllByRole("combobox")[2];
    await user.click(routingButton);

    expect(await screen.findByText("Active Account")).toBeInTheDocument();
    expect(screen.queryByText("Paused Account")).not.toBeInTheDocument();
  });

  it("streams a chat response and shows attached images in the transcript", async () => {
    const user = userEvent.setup();
    streamDashboardChatResponse.mockImplementation(async (_payload, options) => {
      options.onEvent({
        type: "dashboard.chat.started",
        mode: "auto",
        requestedAccountId: null,
        resolvedAccountId: "acc_active",
      });
      options.onEvent({ type: "response.output_text.delta", delta: "Hello there" });
      options.onEvent({ type: "response.completed", response: { id: "resp_1" } });
    });

    const { container } = renderWithProviders(<ChatPage />);
    await screen.findByText("Start a new operator thread");

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement | null;
    expect(fileInput).not.toBeNull();
    const image = new File(["fake"], "photo.png", { type: "image/png" });
    await user.upload(fileInput!, image);

    expect(await screen.findByText("photo.png")).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText("Message the load balancer through a model..."), "Hello");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(streamDashboardChatResponse).toHaveBeenCalledTimes(1);
    });

    expect(await screen.findByText("Hello there")).toBeInTheDocument();
    expect(screen.getByText("Served by Active Account")).toBeInTheDocument();
    expect(screen.getAllByAltText("photo.png")[0]).toBeInTheDocument();
  });

  it("uses the dashboard images endpoint and renders generated output with edit action", async () => {
    const user = userEvent.setup();
    streamDashboardImageConversation.mockImplementation(async (payload, options) => {
      expect(payload.model).toBe("gpt-5.3");
      expect(payload.prompt).toBe("Replace the door");
      options.onEvent({
        type: "dashboard.images.started",
        mode: "auto",
        requestedAccountId: null,
        resolvedAccountId: "acc_active",
      });
      options.onEvent({
        type: "dashboard.images.completed",
        conversationId: "conv_1",
        assistantMessageId: "msg_1",
        parentMessageId: "msg_1",
        assistantText: "Updated as requested",
        images: [
          {
            dataUrl: "data:image/png;base64,ZmFrZQ==",
            mimeType: "image/png",
            filename: "generated-door.png",
            fileId: "file_generated_1",
            originalGenId: "gen_1",
            revisedPrompt: "A bright modern white entrance door",
          },
        ],
      });
    });

    renderWithProviders(<ChatPage />);
    await screen.findByText("Start a new operator thread");

    const modeButton = screen.getAllByRole("combobox")[3];
    await user.click(modeButton);
    await user.click(await screen.findByText("ChatGPT Images"));

    await user.type(
      screen.getByPlaceholderText("Describe the image you want to generate or transform..."),
      "Replace the door",
    );
    await user.click(screen.getByRole("button", { name: "Generate" }));

    await waitFor(() => {
      expect(streamDashboardImageConversation).toHaveBeenCalledTimes(1);
    });

    expect(await screen.findByText("Updated as requested")).toBeInTheDocument();
    expect(screen.getByText("Generated by ChatGPT Images")).toBeInTheDocument();
    expect(screen.getByText("Revised prompt: A bright modern white entrance door")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Edit" }));
    expect(await screen.findByText("Editing generated image: generated-door.png")).toBeInTheDocument();
  });

  it("switching mode on a non-empty thread starts a new thread", async () => {
    const user = userEvent.setup();
    streamDashboardChatResponse.mockImplementation(async (_payload, options) => {
      options.onEvent({ type: "response.completed", response: { id: "resp_1" } });
    });

    renderWithProviders(<ChatPage />);
    await screen.findByText("Start a new operator thread");

    await user.type(screen.getByPlaceholderText("Message the load balancer through a model..."), "Hello");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(streamDashboardChatResponse).toHaveBeenCalledTimes(1);
    });

    const modeButton = screen.getAllByRole("combobox")[3];
    await user.click(modeButton);
    await user.click(await screen.findByText("ChatGPT Images"));

    const threadSelector = screen.getAllByRole("combobox")[0];
    expect(threadSelector).toHaveTextContent("New chat · images");
  });

  it("normalizes stale empty image threads to the preferred image model before sending", async () => {
    const user = userEvent.setup();
    loadChatState.mockResolvedValue({
      threads: [
        {
          id: "thread_1",
          title: "New chat",
          createdAt: "2026-03-29T09:00:00.000Z",
          updatedAt: "2026-03-29T09:00:00.000Z",
          model: "gpt-5.4",
          accountId: null,
          mode: "chatgpt_images",
          conversationId: null,
          parentMessageId: null,
          lastResolvedAccountId: null,
          messages: [],
        },
      ],
    });
    streamDashboardImageConversation.mockImplementation(async (payload) => {
      expect(payload.model).toBe("gpt-5.3");
    });

    renderWithProviders(<ChatPage />);
    await screen.findByText("Start a new operator thread");

    await user.type(
      screen.getByPlaceholderText("Describe the image you want to generate or transform..."),
      "Generate a bright hallway door",
    );
    await user.click(screen.getByRole("button", { name: "Generate" }));

    await waitFor(() => {
      expect(streamDashboardImageConversation).toHaveBeenCalledTimes(1);
    });
  });

  it("blocks image auto-routing when no account has image automation configured", async () => {
    const user = userEvent.setup();
    useAccounts.mockReturnValue({
      accountsQuery: {
        data: [
          {
            accountId: "acc_active",
            email: "active@example.com",
            displayName: "Active Account",
            planType: "plus",
            status: "active",
            chatgptImageSession: {
              status: "disconnected",
              lastValidatedAt: null,
              lastError: null,
            },
            chatgptImageCredentials: {
              configured: false,
              loginEmail: null,
              updatedAt: null,
            },
          },
        ],
        error: null,
      },
    });

    renderWithProviders(<ChatPage />);
    await screen.findByText("Start a new operator thread");

    const modeButton = screen.getAllByRole("combobox")[3];
    await user.click(modeButton);
    await user.click(await screen.findByText("ChatGPT Images"));

    expect(
      await screen.findByText(/No active account has ChatGPT Images automation configured/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate" })).toBeDisabled();
  });
});
