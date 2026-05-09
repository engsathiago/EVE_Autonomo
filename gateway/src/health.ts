import type { FastifyInstance } from "fastify";
import type { CoreClient } from "./core-client.js";
import type { Redis } from "ioredis";

export function registerHealthRoute(
  app: FastifyInstance,
  coreClient: CoreClient,
  redis: Redis,
): void {
  app.get("/health", async (_req, reply) => {
    const [coreOk, redisOk] = await Promise.allSettled([
      coreClient.health(),
      redis.ping().then((r) => r === "PONG"),
    ]);

    const core = coreOk.status === "fulfilled" && coreOk.value ? "reachable" : "unreachable";
    const redisStatus =
      redisOk.status === "fulfilled" && redisOk.value ? "reachable" : "unreachable";

    const allOk = core === "reachable" && redisStatus === "reachable";

    return reply.status(allOk ? 200 : 503).send({
      status: allOk ? "ok" : "degraded",
      core,
      redis: redisStatus,
    });
  });
}
