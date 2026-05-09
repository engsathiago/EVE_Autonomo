import type { Telegraf } from "telegraf";
import type { OutboundMessage } from "../types.js";

export interface ChannelSenders {
  telegram?: Telegraf;
}

export async function routeOutbound(
  msg: OutboundMessage,
  senders: ChannelSenders,
): Promise<void> {
  switch (msg.channel) {
    case "telegram": {
      const bot = senders.telegram;
      if (!bot) throw new Error("Telegram sender not configured");
      await bot.telegram.sendMessage(msg.chat_id, msg.text, {
        reply_markup:
          msg.buttons && msg.buttons.length > 0
            ? {
                inline_keyboard: [
                  msg.buttons.map((b) => ({
                    text: b.text,
                    callback_data: b.callback_data,
                  })),
                ],
              }
            : undefined,
      });
      break;
    }
    default:
      throw new Error(`Unsupported channel: ${msg.channel}`);
  }
}
