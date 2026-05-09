import pino from "pino";
import { Telegraf } from "telegraf";
import type { Allowlist } from "../../auth/allowlist.js";
import type { CoreClient } from "../../core-client.js";
import type { Channel } from "../../types.js";
import {
  buildApprovalKeyboard,
  parseApprovalCallbackData,
} from "./keyboards.js";
import {
  formatApprovalExpired,
  formatApprovalRequest,
  formatApprovalResult,
  formatReply,
} from "./formatters.js";

const log = pino({ name: "telegram-bot" });

export function createTelegramBot(
  token: string,
  coreClient: CoreClient,
  allowlist: Allowlist,
): Telegraf {
  const bot = new Telegraf(token);

  bot.use(async (ctx, next) => {
    const chatId =
      ctx.chat?.id ??
      (ctx.callbackQuery as { message?: { chat?: { id?: number } } })?.message?.chat?.id;

    if (chatId === undefined || !allowlist.allows(chatId)) {
      log.warn({ chatId }, "telegram.blocked: chat_id not in allowlist");
      return; // silent drop
    }
    return next();
  });

  bot.on("text", async (ctx) => {
    const chatId = String(ctx.chat.id);
    const userId = String(ctx.from.id);
    const text = ctx.message.text;
    const sessionId = `tg:${chatId}`;

    log.info({ chatId, sessionId }, "telegram.message.received");

    let typing: ReturnType<typeof setInterval> | undefined;
    try {
      // Show typing indicator while waiting for core
      typing = setInterval(() => {
        ctx.sendChatAction("typing").catch(() => undefined);
      }, 4000);
      ctx.sendChatAction("typing").catch(() => undefined);

      const response = await coreClient.sendMessage({
        session_id: sessionId,
        text,
        channel: "telegram" as Channel,
        user_id: userId,
        metadata: { chat_id: chatId, message_id: String(ctx.message.message_id) },
      });

      clearInterval(typing);

      if (response.type === "approval_request") {
        const keyboard = buildApprovalKeyboard({
          approval_id: response.approval_id!,
        });
        await ctx.reply(
          formatApprovalRequest(response.skill_name ?? "skill", response.summary ?? ""),
          { reply_markup: keyboard, parse_mode: "Markdown" },
        );
      } else {
        await ctx.reply(formatReply(response.text ?? ""));
      }
    } catch (err) {
      clearInterval(typing!);
      log.error({ err, chatId }, "telegram.message.error");
      await ctx.reply(
        "O agente está temporariamente indisponível. Tente novamente em alguns minutos.",
      );
    }
  });

  bot.on("callback_query", async (ctx) => {
    const data = (ctx.callbackQuery as { data?: string }).data;
    if (!data) return;

    const parsed = parseApprovalCallbackData(data);
    if (!parsed) {
      await ctx.answerCbQuery("Ação desconhecida.");
      return;
    }

    const { decision, approvalId } = parsed;
    const userId = String(ctx.from.id);

    await ctx.answerCbQuery(decision === "approve" ? "Aprovando..." : "Rejeitando...");

    try {
      const result = await coreClient.decideApproval(approvalId, decision, userId);

      const replyText = formatApprovalResult(
        result.status as "approved" | "rejected",
        result.result?.output as string | undefined,
      );

      // Edit original message to remove buttons
      if (ctx.callbackQuery.message) {
        await ctx.editMessageReplyMarkup({ inline_keyboard: [] });
      }
      await ctx.reply(replyText);
    } catch (err: unknown) {
      log.error({ err, approvalId }, "telegram.callback_query.error");

      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 409) {
        await ctx.reply(formatApprovalExpired());
        if (ctx.callbackQuery.message) {
          await ctx.editMessageReplyMarkup({ inline_keyboard: [] }).catch(() => undefined);
        }
      } else {
        await ctx.reply("Erro ao processar sua decisão. Tente novamente.");
      }
    }
  });

  return bot;
}
