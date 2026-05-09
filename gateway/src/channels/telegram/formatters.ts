const TG_MAX_LENGTH = 4096;

/**
 * Escapa caracteres especiais do MarkdownV2 do Telegram.
 * https://core.telegram.org/bots/api#markdownv2-style
 */
export function escapeMarkdown(text: string): string {
  return text.replace(/[_*[\]()~`>#+\-=|{}.!\\]/g, "\\$&");
}

/**
 * Trunca texto para o limite do Telegram, adicionando sufixo se necessário.
 */
export function truncate(text: string, maxLen = TG_MAX_LENGTH): string {
  if (text.length <= maxLen) return text;
  const suffix = "\n…";
  return text.slice(0, maxLen - suffix.length) + suffix;
}

/**
 * Formata uma resposta do agente para envio via Telegram.
 * Usa parse_mode=undefined (plain text) para máxima compatibilidade.
 */
export function formatReply(text: string): string {
  return truncate(text);
}

export function formatApprovalRequest(skillName: string, summary: string): string {
  return truncate(
    `🔐 *Aprovação necessária*\n\nA skill \`${skillName}\` requer sua aprovação antes de executar:\n\n${summary}`,
  );
}

export function formatApprovalExpired(): string {
  return "⏱ Esta ação expirou. Envie a solicitação novamente se ainda for necessário.";
}

export function formatApprovalResult(status: "approved" | "rejected", output?: string): string {
  if (status === "rejected") return "❌ Ação rejeitada.";
  const base = "✅ Ação aprovada e executada.";
  if (output) return `${base}\n\n${truncate(output, 3000)}`;
  return base;
}
