import type { Redis } from "ioredis";
import Bottleneck from "bottleneck";
import pino from "pino";
import type { ChannelSenders } from "./router.js";
import { routeOutbound } from "./router.js";
import type { OutboundMessage } from "../types.js";

const log = pino({ name: "outbound-worker" });

const QUEUE_KEY = "outbound:telegram";
const BRPOP_TIMEOUT_S = 5;

// Telegram allows 30 messages/second globally
const limiter = new Bottleneck({ maxConcurrent: 1, minTime: 40 });

export class OutboundWorker {
  private running = false;
  private loopPromise: Promise<void> | null = null;

  constructor(
    private readonly redis: Redis,
    private readonly senders: ChannelSenders,
  ) {}

  start(): void {
    if (this.running) return;
    this.running = true;
    this.loopPromise = this._loop();
    log.info("outbound.worker.started");
  }

  async stop(): Promise<void> {
    this.running = false;
    if (this.loopPromise) await this.loopPromise;
    log.info("outbound.worker.stopped");
  }

  private async _loop(): Promise<void> {
    while (this.running) {
      try {
        const item = await this.redis.brpop(QUEUE_KEY, BRPOP_TIMEOUT_S);
        if (!item) continue;

        const [, raw] = item;
        let msg: OutboundMessage;

        try {
          msg = JSON.parse(raw) as OutboundMessage;
        } catch {
          log.error({ raw }, "outbound.worker.parse_error");
          continue;
        }

        await limiter.schedule(() => this._dispatch(msg));
      } catch (err) {
        if (!this.running) break;
        log.error({ err }, "outbound.worker.loop_error");
        // Brief pause to avoid tight loop on persistent errors
        await new Promise((r) => setTimeout(r, 1000));
      }
    }
  }

  private async _dispatch(msg: OutboundMessage): Promise<void> {
    try {
      await routeOutbound(msg, this.senders);
      log.info({ channel: msg.channel, chat_id: msg.chat_id }, "outbound.dispatched");
    } catch (err) {
      log.error({ err, msg }, "outbound.dispatch_failed");
      // Re-enqueue with backoff for retryable errors
      const isRateLimit =
        (err as { code?: string | number }).code === 429 ||
        String(err).includes("429");
      if (isRateLimit) {
        await new Promise((r) => setTimeout(r, 5000));
        await this.redis.lpush(QUEUE_KEY, JSON.stringify(msg));
        log.warn({ chat_id: msg.chat_id }, "outbound.requeued_after_rate_limit");
      }
    }
  }
}
