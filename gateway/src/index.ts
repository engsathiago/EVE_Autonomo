import Fastify from "fastify";
import { Redis } from "ioredis";
import { z } from "zod";

import { registerChatRoutes } from "./routes/chat.js";

const EnvSchema = z.object({
  PORT: z.coerce.number().default(8001),
  REDIS_URL: z.string().default("redis://redis:6379/0"),
  CORE_URL: z.string().default("http://core:8000"),
});

const env = EnvSchema.parse(process.env);
process.env.CORE_URL = env.CORE_URL;

const app = Fastify({ logger: true });

const redis = new Redis(env.REDIS_URL, {
  lazyConnect: true,
  maxRetriesPerRequest: 3,
});

redis.on("error", (err: Error) => {
  app.log.error({ err }, "Redis connection error");
});

app.get("/health", async () => {
  const redisPing = await redis.ping().catch(() => "FAIL");
  return { ok: redisPing === "PONG" };
});

registerChatRoutes(app);

const start = async (): Promise<void> => {
  try {
    await redis.connect();
    app.log.info("Redis connected");

    await app.listen({ port: env.PORT, host: "0.0.0.0" });
  } catch (err) {
    app.log.error(err);
    process.exit(1);
  }
};

start();
