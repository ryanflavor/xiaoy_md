import clsx from "clsx";

import { ApiError } from "@/services/apiClient";

export type ApiErrorCopy = {
  primaryEn: string;
  primaryZh: string;
  helperEn: string;
  helperZh: string;
  detail?: string;
};

type ErrorBannerProps = {
  error: unknown;
  className?: string;
};

export function ErrorBanner({ error, className }: ErrorBannerProps) {
  const copy = resolveApiError(error);

  return (
    <div
      className={clsx(
        "rounded-xl border border-danger/40 bg-danger/10 p-4 text-sm",
        "shadow-inner shadow-danger/20",
        className,
      )}
    >
      <p className="text-base font-semibold text-danger">
        {copy.primaryEn}
        <span className="ml-2 text-neutral-400">{copy.primaryZh}</span>
      </p>
      <p className="mt-2 text-neutral-200">
        {copy.helperEn}
        <span className="ml-2 text-neutral-500">{copy.helperZh}</span>
      </p>
      {copy.detail ? (
        <p className="mt-3 whitespace-pre-wrap rounded bg-neutral-950/50 p-3 text-xs text-neutral-400">
          {copy.detail}
        </p>
      ) : null}
    </div>
  );
}

export function resolveApiError(error: unknown): ApiErrorCopy {
  if (error instanceof ApiError) {
    return translateStatus(error.status, error.message);
  }

  if (error instanceof TypeError) {
    const detail = error.message || undefined;
    return {
      primaryEn: "Cannot reach operations API",
      primaryZh: "无法连接运维 API",
      helperEn: "Check that ops-api is running and the dev proxy is configured.",
      helperZh: "请确认 ops-api 服务已启动并正确配置开发代理。",
      detail,
    };
  }

  const detail = getReadableDetail(error);
  return {
    primaryEn: "Unexpected operations console error",
    primaryZh: "控制台发生未知错误",
    helperEn: "Retry the request or inspect browser logs for more context.",
    helperZh: "请重试请求，如仍失败请查看浏览器日志。",
    detail,
  };
}

function translateStatus(status: number, detail: string | undefined): ApiErrorCopy {
  if (status === 401) {
    return {
      primaryEn: "Unauthorized request",
      primaryZh: "请求未授权",
      helperEn: "Verify VITE_OPS_API_TOKEN matches the ops-api configuration.",
      helperZh: "请确认 VITE_OPS_API_TOKEN 与后端配置一致。",
      detail,
    };
  }
  if (status === 403) {
    return {
      primaryEn: "Access forbidden",
      primaryZh: "拒绝访问",
      helperEn: "Current token is not permitted to execute runbooks.",
      helperZh: "当前令牌无权限执行 Runbook 操作。",
      detail,
    };
  }
  if (status >= 500) {
    return {
      primaryEn: "Operations API unavailable",
      primaryZh: "运维 API 不可用",
      helperEn: "Service may be warming up or offline. Check the ops-api container before retrying.",
      helperZh: "服务可能初始化中或已停止，请检查 ops-api 容器后重试。",
      detail,
    };
  }
  if (status === 429) {
    return {
      primaryEn: "Too many requests",
      primaryZh: "请求过于频繁",
      helperEn: "Wait briefly before sending another runbook command.",
      helperZh: "请稍候再发起新 Runbook 请求。",
      detail,
    };
  }
  return {
    primaryEn: `Request failed (${status})`,
    primaryZh: `请求失败 (${status})`,
    helperEn: "See the detailed message for troubleshooting guidance.",
    helperZh: "请查看详细信息以定位问题。",
    detail,
  };
}

function getReadableDetail(error: unknown): string | undefined {
  if (!error) {
    return undefined;
  }
  if (typeof error === "string") {
    return error;
  }
  if (error instanceof Error) {
    return error.message;
  }
  try {
    return JSON.stringify(error);
  } catch (serializationError) {
    return String(error);
  }
}
