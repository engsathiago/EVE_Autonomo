import { describe, it, expect, vi, beforeEach } from "vitest";
import { OutboundWorker } from "../src/outbound/worker.js";
import type { OutboundMessage } from "../src/types.js";

function makeRedis(messages: string[] = []) {
  let callCount = 0;
  const brpop = vi.fn().mockImplementation(async (_key: string, _timeout: number) => {
    const msg = messages[callCount++];
    if (msg !== undefined) return ["outbound:telegram", msg];
    // Return null after all messages, with a small delay to prevent tight loop
    await new Promise((r) => setTimeout(r, 50));
    return null;
  });
  const lpush = vi.fn().mockResolvedValue(1);
  return { brpop, lpush } as unknown as import("ioredis").Redis;
}

function makeBot() {
  return {
    telegram: {
      sendMessage: vi.fn().mockResolvedValue({ message_id: 1 }),
    },
  };
}

describe("OutboundWorker", () => {
  it("dispatches telegram message from queue", async () => {
    const msg: OutboundMessage = {
      channel: "telegram",
      chat_id: "456",
      text: "Hello from agent",
    };
    const redis = makeRedis([JSON.stringify(msg)]);
    const bot = makeBot();
    const worker = new OutboundWorker(redis, { telegram: bot as never });

    worker.start();
    // Wait for the message to be dispatched
    await new Promise((r) => setTimeout(r, 200));
    await worker.stop();

    expect(bot.telegram.sendMessage).toHaveBeenCalledWith(
      "456",
      "Hello from agent",
      expect.anything(),
    );
  });

  it("skips malformed JSON payload without crashing", async () => {
    const redis = makeRedis(["not-valid-json"]);
    const bot = makeBot();
    const worker = new OutboundWorker(redis, { telegram: bot as never });

    worker.start();
    await new Promise((r) => setTimeout(r, 200));
    await worker.stop();

    expect(bot.telegram.sendMessage).not.toHaveBeenCalled();
  });

  it("re-enqueues message on Telegram rate limit (429)", async () => {
    const msg: OutboundMessage = {
      channel: "telegram",
      chat_id: "789",
      text: "Rate limited",
    };
    const redis = makeRedis([JSON.stringify(msg)]);
    const bot = makeBot();
    const err = Object.assign(new Error("Too Many Requests"), { code: 429 });
    bot.telegram.sendMessage.mockRejectedValueOnce(err);

    const worker = new OutboundWorker(redis, { telegram: bot as never });
    worker.start();
    await new Promise((r) => setTimeout(r, 6500)); // backoff is 5s
    await worker.stop();

    expect((redis as { lpush: ReturnType<typeof vi.fn> }).lpush).toHaveBeenCalledWith(
      "outbound:telegram",
      JSON.stringify(msg),
    );
  }, 10000);
});
