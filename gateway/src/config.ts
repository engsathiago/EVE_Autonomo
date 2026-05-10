import { z } from "zod";

const EnvSchema = z.object({
  PORT: z.coerce.number().default(3000),
  REDIS_URL: z.string().default("redis://redis:6379/0"),
  CORE_URL: z.string().default("http://core:8000"),
  TELEGRAM_BOT_TOKEN: z.string().min(1, "TELEGRAM_BOT_TOKEN is required"),
  TELEGRAM_ALLOWED_CHAT_IDS: z.string().default(""),
  LOG_LEVEL: z.string().default("info"),
  CORE_TIMEOUT_MS: z.coerce.number().default(30000),
  CORE_RETRY_COUNT: z.coerce.number().default(3),
});

export type Config = z.infer<typeof EnvSchema>;

export function loadConfig(): Config {
  const result = EnvSchema.safeParse(process.env);
  if (!result.success) {
    const missing = result.error.issues.map((i) => i.path.join(".")).join(", ");
    throw new Error(`Missing/invalid env vars: ${missing}`);
  }
  return result.data;
}

export function maskToken(token: string): string {
  if (token.length < 10) return "***";
  return token.slice(0, 6) + "***" + token.slice(-4);
}
