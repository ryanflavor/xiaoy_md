import dayjs from "dayjs";
import utc from "dayjs/plugin/utc.js";
import timezone from "dayjs/plugin/timezone.js";

dayjs.extend(utc);
dayjs.extend(timezone);

type HttpMethod = "GET" | "POST";

type OpsEnv = {
  VITE_OPS_API_BASE_URL?: string;
  VITE_OPS_API_TOKEN?: string;
};

function resolveEnv(): OpsEnv {
  try {
    const meta = import.meta as { env?: OpsEnv };
    if (meta?.env) {
      return meta.env;
    }
  } catch (error) {
    // `import.meta` is unavailable in some Node-driven contexts (e.g., Playwright workers)
  }

  if (typeof globalThis !== "undefined") {
    const globalEnv = (globalThis as { __OPS_ENV__?: OpsEnv }).__OPS_ENV__;
    if (globalEnv) {
      return globalEnv;
    }
  }

  if (typeof process !== "undefined" && process.env) {
    return {
      VITE_OPS_API_BASE_URL: process.env.VITE_OPS_API_BASE_URL,
      VITE_OPS_API_TOKEN: process.env.VITE_OPS_API_TOKEN,
    } satisfies OpsEnv;
  }

  return {};
}

const env = resolveEnv();

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const baseUrl = env.VITE_OPS_API_BASE_URL ?? "/api";
const apiToken = env.VITE_OPS_API_TOKEN ?? "";

async function request<T>(path: string, method: HttpMethod, body?: unknown): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(apiToken ? { Authorization: `Bearer ${apiToken}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    const detail = await safeParseError(response);
    throw new ApiError(detail ?? response.statusText, response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

async function safeParseError(response: Response): Promise<string | undefined> {
  try {
    const payload = await response.json();
    if (typeof payload === "string") {
      return payload;
    }
    if (payload && typeof payload.detail === "string") {
      return payload.detail;
    }
  } catch (error) {
    return undefined;
  }
  return undefined;
}

export function getJson<T>(path: string): Promise<T> {
  return request<T>(path, "GET");
}

export function postJson<T, P = unknown>(path: string, body: P): Promise<T> {
  return request<T>(path, "POST", body);
}

export function isoTimestamp(date: string | Date): string {
  const ts = typeof date === "string" ? dayjs(date) : dayjs(date.toISOString());
  return ts.tz("Asia/Shanghai").format("YYYY-MM-DD HH:mm:ss Z");
}
