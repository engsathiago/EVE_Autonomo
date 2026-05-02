import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { z } from "zod";

const ChatRequestSchema = z.object({
  message: z.string().min(1),
  conversation_id: z.string().uuid().optional(),
});

const ChatResponseSchema = z.object({
  text: z.string(),
  iterations: z.number(),
  input_tokens: z.number(),
  output_tokens: z.number(),
  estimated_cost_usd: z.number(),
  duration_s: z.number(),
  conversation_id: z.string(),
});

type ChatRequest = z.infer<typeof ChatRequestSchema>;

const CORE_URL = process.env.CORE_URL ?? "http://core:8000";

async function chatHandler(
  req: FastifyRequest<{ Body: ChatRequest }>,
  reply: FastifyReply,
): Promise<void> {
  const body = ChatRequestSchema.parse(req.body);

  let coreRes: Response;
  try {
    coreRes = await fetch(`${CORE_URL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: body.message,
        conversation_id: body.conversation_id ?? null,
      }),
    });
  } catch (err) {
    req.log.error({ err }, "core unreachable");
    return reply.status(502).send({ error: "core_unreachable" });
  }

  if (!coreRes.ok) {
    const text = await coreRes.text().catch(() => "");
    req.log.error({ status: coreRes.status, body: text }, "core error");
    return reply.status(coreRes.status).send({ error: "core_error", detail: text });
  }

  const data = await coreRes.json();
  return reply.send(ChatResponseSchema.parse(data));
}

export function registerChatRoutes(app: FastifyInstance): void {
  app.post<{ Body: ChatRequest }>("/api/chat", chatHandler);
}
