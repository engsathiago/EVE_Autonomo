export class Allowlist {
  private readonly ids: Set<string>;
  private readonly open: boolean;

  constructor(rawCsv: string) {
    const trimmed = rawCsv.trim();
    if (!trimmed) {
      // Empty string = open (development mode, no restriction)
      this.ids = new Set();
      this.open = true;
    } else {
      this.ids = new Set(trimmed.split(",").map((s) => s.trim()).filter(Boolean));
      this.open = false;
    }
  }

  allows(chatId: string | number): boolean {
    if (this.open) return true;
    return this.ids.has(String(chatId));
  }

  get isOpen(): boolean {
    return this.open;
  }
}
