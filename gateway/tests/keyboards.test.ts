import { describe, it, expect } from "vitest";
import {
  buildApprovalKeyboard,
  parseApprovalCallbackData,
} from "../src/channels/telegram/keyboards.js";

describe("buildApprovalKeyboard", () => {
  it("returns inline keyboard with two buttons", () => {
    const kb = buildApprovalKeyboard({ approval_id: "abc-123" });
    expect(kb.inline_keyboard).toHaveLength(1);
    expect(kb.inline_keyboard[0]).toHaveLength(2);
  });

  it("button callback_data contains approval_id", () => {
    const kb = buildApprovalKeyboard({ approval_id: "my-id" });
    const [approve, reject] = kb.inline_keyboard[0];
    expect(approve.callback_data).toBe("approval:approve:my-id");
    expect(reject.callback_data).toBe("approval:reject:my-id");
  });

  it("uses custom labels when provided", () => {
    const kb = buildApprovalKeyboard({
      approval_id: "x",
      approve_label: "Sim",
      reject_label: "Não",
    });
    expect(kb.inline_keyboard[0][0].text).toBe("Sim");
    expect(kb.inline_keyboard[0][1].text).toBe("Não");
  });
});

describe("parseApprovalCallbackData", () => {
  it("parses approve callback", () => {
    const result = parseApprovalCallbackData("approval:approve:abc-123");
    expect(result).toEqual({ decision: "approve", approvalId: "abc-123" });
  });

  it("parses reject callback", () => {
    const result = parseApprovalCallbackData("approval:reject:xyz");
    expect(result).toEqual({ decision: "reject", approvalId: "xyz" });
  });

  it("returns null for unknown data", () => {
    expect(parseApprovalCallbackData("something_else")).toBeNull();
    expect(parseApprovalCallbackData("")).toBeNull();
  });

  it("handles approval_id with hyphens and uuids", () => {
    const uuid = "550e8400-e29b-41d4-a716-446655440000";
    const result = parseApprovalCallbackData(`approval:approve:${uuid}`);
    expect(result?.approvalId).toBe(uuid);
  });
});
