/**
 * Durations for the upload-items summary.  A row skipped as "haben wir schon"
 * was never processed, so its near-zero duration must not drag down the
 * average per processed item.  Rows without a duration (parser rejects,
 * duplicates, still queued) are excluded as well.
 */

export const ALREADY_LISTED_REASON = "haben wir schon";

const ALREADY_LISTED_STATES = new Set(["skipped_existing", "already_listed"]);

export type UploadDurationRow = {
  state: string;
  reason?: string;
  started_at?: string;
  duration_sec?: number | null;
};

export type UploadDurationStats = {
  processed: number;
  totalSec: number;
  averageSec: number | null;
};

export function isAlreadyListedRow(row: UploadDurationRow): boolean {
  return (
    ALREADY_LISTED_STATES.has(row.state) ||
    (row.reason ?? "").trim() === ALREADY_LISTED_REASON
  );
}

/** Finished rows use the recorded monotonic duration; the running row ticks. */
export function rowDurationSeconds(
  row: UploadDurationRow,
  nowMs: number,
  live: boolean,
): number | null {
  if (typeof row.duration_sec === "number" && Number.isFinite(row.duration_sec)) {
    return row.duration_sec;
  }
  if (!live || !row.started_at) {
    return null;
  }
  const started = Date.parse(row.started_at);
  if (Number.isNaN(started)) {
    return null;
  }
  return Math.max(0, (nowMs - started) / 1000);
}

export function uploadDurationStats(
  rows: UploadDurationRow[],
  nowMs: number,
  live: boolean,
): UploadDurationStats {
  const durations: number[] = [];
  for (const row of rows) {
    if (isAlreadyListedRow(row)) {
      continue;
    }
    const duration = rowDurationSeconds(row, nowMs, live);
    if (duration !== null) {
      durations.push(duration);
    }
  }
  const totalSec = durations.reduce((sum, value) => sum + value, 0);
  return {
    processed: durations.length,
    totalSec,
    averageSec: durations.length ? totalSec / durations.length : null,
  };
}
