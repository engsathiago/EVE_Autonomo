import Fastify from "fastify";
import { Redis } from "ioredis";
import pino from "pino";

import { loadConfig, maskToken } from "./config.js";
import { CoreClient } from "./core-client.js";
import { Allowlist } from "./auth/allowlist.js";
import { createTelegramBot } from "./channels/telegram/bot.js";
import { OutboundWorker } from "./outbound/worker.js";
import { registerHealthRoute } from "./health.js";

const log = pino({ name: "gateway" });

const start = async (): Promise<void> => {
  const config = loadConfig();

  log.info(
    { port: config.PORT, token: maskToken(config.TELEGRAM_BOT_TOKEN) },
    "gateway.starting",
  );

  const redis = new Redis(config.REDIS_URL, {
    lazyConnect: true,
    maxRetriesPerRequest: 3,
  });

  redis.on("error", (err: Error) => log.error({ err }, "redis.error"));

  const coreClient = new CoreClient(config);
  const allowlist = new Allowlist(config.TELEGRAM_ALLOWED_CHAT_IDS);

  if (allowlist.isOpen) {
    log.warn("auth.allowlist.open: all chat_ids accepted — set TELEGRAM_ALLOWED_CHAT_IDS for production");
  }

  const bot = createTelegramBot(config.TELEGRAM_BOT_TOKEN, coreClient, allowlist);

  const worker = new OutboundWorker(redis, { telegram: bot });

  const app = Fastify({ logger: false });

  registerHealthRoute(app, coreClient, redis);

  try {
    await redis.connect();
    log.info("redis.connected");

    await app.listen({ port: config.PORT, host: "0.0.0.0" });
    log.info({ port: config.PORT }, "http.listening");

    worker.start();

    await bot.launch();
    log.info("telegram.bot.launched");

    const shutdown = async (signal: string): Promise<void> => {
      log.info({ signal }, "gateway.shutting_down");
      bot.stop(signal);
      await worker.stop();
      await app.close();
      await redis.quit();
      process.exit(0);
    };

    process.once("SIGINT", () => shutdown("SIGINT"));
    process.once("SIGTERM", () => shutdown("SIGTERM"));
  } catch (err) {
    log.error({ err }, "gateway.start_failed");
    process.exit(1);
  }
};

start();
