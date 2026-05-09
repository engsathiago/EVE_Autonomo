import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import axios from "axios";
import { CoreClient, CoreUnavailableError } from "../src/core-client.js";

vi.mock("axios");
vi.mock("axios-retry", () => ({
  default: vi.fn(),
  exponentialDelay: vi.fn(),
  isNetworkOrIdempotentRequestError: vi.fn(() => false),
}));

const mockAxiosCreate = vi.mocked(axios.create);

function makeClient() {
  const mockInstance = {
    post: vi.fn(),
    get: vi.fn(),
  };
  mockAxiosCreate.mockReturnValue(mockInstance as unknown as typeof axios);
  return { client: new CoreClient({ CORE_URL: "http://core:8000", CORE_TIMEOUT_MS: 5000, CORE_RETRY_COUNT: 1 }), mock: mockInstance };
}

describe("CoreClient.sendMessage", () => {
  it("returns parsed response on success", async () => {
    const { client, mock } = makeClient();
    mock.post.mockResolvedValue({
      data: { type: "reply", text: "Olá!" },
    });

    const result = await client.sendMessage({
      session_id: "tg:123",
      text: "oi",
      channel: "telegram",
      user_id: "123",
    });

    expect(result.type).toBe("reply");
    expect(result.text).toBe("Olá!");
    expect(mock.post).toHaveBeenCalledWith("/v1/messages", expect.objectContaining({ text: "oi" }));
  });

  it("throws CoreUnavailableError on network failure", async () => {
    const { client, mock } = makeClient();
    mock.post.mockRejectedValue(new Error("ECONNREFUSED"));

    await expect(
      client.sendMessage({ session_id: "tg:1", text: "hi", channel: "telegram", user_id: "1" }),
    ).rejects.toThrow(CoreUnavailableError);
  });

  it("returns approval_request response", async () => {
    const { client, mock } = makeClient();
    mock.post.mockResolvedValue({
      data: {
        type: "approval_request",
        approval_id: "abc-123",
        skill_name: "mock_send_email",
        summary: "Enviar email",
      },
    });

    const result = await client.sendMessage({
      session_id: "tg:99",
      text: "manda email pro chefe",
      channel: "telegram",
      user_id: "99",
    });

    expect(result.type).toBe("approval_request");
    expect(result.approval_id).toBe("abc-123");
  });
});

describe("CoreClient.decideApproval", () => {
  it("sends decision to core and returns status", async () => {
    const { client, mock } = makeClient();
    mock.post.mockResolvedValue({ data: { status: "approved", result: { output: "done" } } });

    const result = await client.decideApproval("abc", "approve", "user1");
    expect(result.status).toBe("approved");
    expect(mock.post).toHaveBeenCalledWith("/v1/approvals/abc", {
      decision: "approve",
      decided_by: "user1",
    });
  });

  it("throws CoreUnavailableError on failure", async () => {
    const { client, mock } = makeClient();
    mock.post.mockRejectedValue(new Error("timeout"));

    await expect(client.decideApproval("x", "reject", "u")).rejects.toThrow(CoreUnavailableError);
  });
});
