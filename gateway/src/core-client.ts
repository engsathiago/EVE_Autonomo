import axios, { AxiosError, AxiosInstance } from "axios";
import axiosRetry, { exponentialDelay, isNetworkOrIdempotentRequestError } from "axios-retry";
import type { Config } from "./config.js";
import type { CoreDecisionResponse, CoreMessageResponse, InboundMessage } from "./types.js";

export class CoreUnavailableError extends Error {
  constructor(
    message: string,
    public readonly cause?: unknown,
  ) {
    super(message);
    this.name = "CoreUnavailableError";
  }
}

export class CoreClient {
  private readonly http: AxiosInstance;

  constructor(config: Pick<Config, "CORE_URL" | "CORE_TIMEOUT_MS" | "CORE_RETRY_COUNT">) {
    this.http = axios.create({
      baseURL: config.CORE_URL,
      timeout: config.CORE_TIMEOUT_MS,
      headers: { "Content-Type": "application/json" },
    });

    axiosRetry(this.http, {
      retries: config.CORE_RETRY_COUNT,
      retryDelay: exponentialDelay,
      retryCondition: (err: AxiosError) => {
        if (isNetworkOrIdempotentRequestError(err)) return true;
        const status = err.response?.status;
        return status === 502 || status === 503 || status === 504;
      },
      onRetry: (retryCount, err) => {
        // log is injected externally; just annotate for now
        process.stderr.write(
          `[core-client] retry ${retryCount} after ${err.message}\n`,
        );
      },
    });
  }

  async sendMessage(msg: InboundMessage): Promise<CoreMessageResponse> {
    try {
      const res = await this.http.post<CoreMessageResponse>("/v1/messages", msg);
      return res.data;
    } catch (err) {
      throw new CoreUnavailableError(
        `Core unreachable after retries: ${(err as Error).message}`,
        err,
      );
    }
  }

  async decideApproval(
    approvalId: string,
    decision: "approve" | "reject",
    decidedBy: string,
  ): Promise<CoreDecisionResponse> {
    try {
      const res = await this.http.post<CoreDecisionResponse>(`/v1/approvals/${approvalId}`, {
        decision,
        decided_by: decidedBy,
      });
      return res.data;
    } catch (err) {
      throw new CoreUnavailableError(
        `Core unreachable when deciding approval: ${(err as Error).message}`,
        err,
      );
    }
  }

  async health(): Promise<boolean> {
    try {
      await this.http.get("/health", { timeout: 5000 });
      return true;
    } catch {
      return false;
    }
  }
}
