import { useState } from "react";
import clsx from "clsx";
import { useRunbookMutation } from "@/hooks/useOperationsData";
import { resolveApiError } from "./ErrorBanner";
import type { RunbookCommandPayload } from "@/services/types";
import { isoTimestamp } from "@/services/apiClient";

export type ActionPanelProps = {
  titleEn: string;
  titleZh: string;
  descriptionEn: string;
  descriptionZh: string;
  actionLabelEn: string;
  actionLabelZh: string;
  payload: Partial<RunbookCommandPayload>;
  confirmationMessage?: string;
  dryRunPreview?: string;
};

export function ActionPanel({
  titleEn,
  titleZh,
  descriptionEn,
  descriptionZh,
  actionLabelEn,
  actionLabelZh,
  payload,
  confirmationMessage,
  dryRunPreview,
}: ActionPanelProps) {
  const mutation = useRunbookMutation();
  const [showConfirm, setShowConfirm] = useState(false);
  const [latestResult, setLatestResult] = useState<string | null>(null);
  const mutationError = mutation.isError ? resolveApiError(mutation.error) : null;

  const trigger = () => {
    setShowConfirm(true);
  };

  const confirm = async () => {
    try {
      const response = await mutation.mutateAsync(payload);
      const message = formatRunbookResponse(response);
      setLatestResult(message);
    } finally {
      setShowConfirm(false);
    }
  };

  return (
    <section className="card-surface flex flex-col gap-4">
      <header>
        <h3 className="text-lg font-semibold text-neutral-100">
          {titleEn}
          <span className="ml-2 text-sm text-neutral-500">{titleZh}</span>
        </h3>
      </header>
      <p className="text-sm text-neutral-300">
        {descriptionEn}
        <span className="ml-2 text-neutral-500">{descriptionZh}</span>
      </p>
      {dryRunPreview ? (
        <div className="rounded-xl border border-primary/30 bg-primary/5 p-3 text-xs text-primary">
          {dryRunPreview}
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className={clsx("button-primary", {
            "opacity-60": mutation.isPending,
            "pointer-events-none": mutation.isPending,
          })}
          onClick={trigger}
        >
          {actionLabelEn} / {actionLabelZh}
        </button>
        {mutationError ? (
          <div className="text-sm text-danger">
            <div>
              {mutationError.primaryEn}
              <span className="ml-2 text-neutral-400">{mutationError.primaryZh}</span>
            </div>
            <div className="text-xs text-neutral-400">
              {mutationError.helperEn}
              <span className="ml-2 text-neutral-500">{mutationError.helperZh}</span>
            </div>
            {mutationError.detail ? (
              <div className="mt-1 text-xs text-neutral-500">
                {mutationError.detail}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
      {latestResult ? (
        <div className="rounded-xl border border-neutral-700 bg-neutral-900/60 p-3 text-xs text-neutral-300">
          {latestResult}
        </div>
      ) : null}
      {showConfirm ? (
        <dialog open className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <div className="w-full max-w-md rounded-2xl bg-surface p-6 shadow-card">
            <h4 className="mb-2 text-lg font-semibold text-neutral-100">
              Confirm Action / 操作确认
            </h4>
            <p className="text-sm text-neutral-300">
              {confirmationMessage ??
                "Please confirm this runbook action will execute with least privilege safeguards./请确认即将执行的 Runbook 操作"}
            </p>
            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                className="rounded-md border border-neutral-600 px-4 py-2 text-sm text-neutral-200"
                onClick={() => setShowConfirm(false)}
              >
                Cancel / 取消
              </button>
              <button
                type="button"
                className="button-primary"
                onClick={confirm}
              >
                Execute / 执行
              </button>
            </div>
          </div>
        </dialog>
      ) : null}
    </section>
  );
}

function formatRunbookResponse(response: Awaited<ReturnType<typeof useRunbookMutation>["mutateAsync"]>) {
  const executedAt = isoTimestamp(response.runbook.finished_at);
  const exitCode = response.runbook.exit_code;
  const command = response.runbook.command;
  return `Runbook ${command} completed at ${executedAt} (exit=${exitCode}).`; // zh fallback optional
}
