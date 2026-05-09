import { describe, it, expect } from "vitest";
import { Allowlist } from "../src/auth/allowlist.js";

describe("Allowlist", () => {
  it("blocks chat_id not in list", () => {
    const list = new Allowlist("111,222");
    expect(list.allows("333")).toBe(false);
    expect(list.allows(333)).toBe(false);
  });

  it("allows chat_id in list", () => {
    const list = new Allowlist("111,222");
    expect(list.allows("111")).toBe(true);
    expect(list.allows(222)).toBe(true);
  });

  it("allows all when list is empty (open mode)", () => {
    const list = new Allowlist("");
    expect(list.allows("999")).toBe(true);
    expect(list.isOpen).toBe(true);
  });

  it("allows all when list is whitespace only", () => {
    const list = new Allowlist("   ");
    expect(list.allows("999")).toBe(true);
  });

  it("trims spaces from ids", () => {
    const list = new Allowlist(" 111 , 222 ");
    expect(list.allows("111")).toBe(true);
    expect(list.allows("222")).toBe(true);
  });
});
