export type Channel = "telegram" | "slack" | "discord" | "cli";

export interface InboundMessage {
  session_id: string;
  text: string;
  channel: Channel;
  user_id: string;
  metadata?: Record<string, unknown>;
}

export interface CoreMessageResponse {
  type: "reply" | "approval_request";
  text?: string;
  approval_id?: string;
  skill_name?: string;
  summary?: string;
  expires_at?: string;
  conversation_id?: string;
}

export interface CoreDecisionResponse {
  status: "approved" | "rejected";
  result?: Record<string, unknown>;
}

export interface OutboundMessage {
  session_id?: string;
  channel: Channel;
  chat_id: string;
  text: string;
  buttons?: ButtonRow[];
  idempotency_key?: string;
  metadata?: Record<string, unknown>;
}

export interface ButtonRow {
  text: string;
  callback_data: string;
}

export interface ApprovalButtons {
  approval_id: string;
  approve_label?: string;
  reject_label?: string;
}
