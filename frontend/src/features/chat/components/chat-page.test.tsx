import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatPage } from "@/features/chat/components/chat-page";
import { renderWithProviders } from "@/test/utils";

const {
  streamDashboardChatResponse,
  loadChatState,
  saveChatState,
  loadChatPreferences,
  saveChatPreferences,
  useAccounts,
  useModels,
} = vi.hoisted(() => ({
  streamDashboardChatResponse: vi.fn(),
  loadChatState: vi.fn(),
  saveChatState: vi.fn(),
  loadChatPreferences: vi.fn(),
  saveChatPreferences: vi.fn(),
  useAccounts: vi.fn(),
  useModels: vi.fn(),
}));

vi.mock("@/features/chat/api", () => ({
  streamDashboardChatResponse,
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
    loadChatState.mockResolvedValue({ threads: [] });
    saveChatState.mockResolvedValue(undefined);
    loadChatPreferences.mockReturnValue({
      activeThreadId: null,
      lastModel: null,
      lastAccount: null,
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
          },
          {
            accountId: "acc_paused",
            email: "paused@example.com",
            displayName: "Paused Account",
            planType: "plus",
            status: "paused",
          },
        ],
        error: null,
      },
    });
    useModels.mockReturnValue({
      data: [{ id: "gpt-5.1", name: "GPT 5.1" }],
      error: null,
    });
  });

  it("shows auto routing plus active accounts only in the selector", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ChatPage />);

    await screen.findByText("Start a new operator chat");

    const routingButton = screen.getAllByRole("combobox")[2];
    await user.click(routingButton!);

    expect(await screen.findByText("Active Account")).toBeInTheDocument();
    expect(screen.queryByText("Paused Account")).not.toBeInTheDocument();
  });

  it("streams a response and shows attached images in the transcript", async () => {
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
    await screen.findByText("Start a new operator chat");

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
});
