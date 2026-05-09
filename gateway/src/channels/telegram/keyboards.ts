import type { InlineKeyboardMarkup } from "telegraf/types";
import type { ApprovalButtons } from "../../types.js";

export function buildApprovalKeyboard(opts: ApprovalButtons): InlineKeyboardMarkup {
  return {
    inline_keyboard: [
      [
        {
          text: opts.approve_label ?? "✅ Aprovar",
          callback_data: `approval:approve:${opts.approval_id}`,
        },
        {
          text: opts.reject_label ?? "❌ Rejeitar",
          callback_data: `approval:reject:${opts.approval_id}`,
        },
      ],
    ],
  };
}

export function parseApprovalCallbackData(
  data: string,
): { decision: "approve" | "reject"; approvalId: string } | null {
  const match = data.match(/^approval:(approve|reject):(.+)$/);
  if (!match) return null;
  return { decision: match[1] as "approve" | "reject", approvalId: match[2] };
}
