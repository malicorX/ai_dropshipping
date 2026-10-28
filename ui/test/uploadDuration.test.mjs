import assert from "node:assert/strict";
import test from "node:test";

import {
  previewFileToLoad,
  rowDurationSeconds,
  runRowsMatchSelectedFile,
  uploadDurationStats,
} from "../.test-build/uploadDuration.js";

test("summary excludes 'haben wir schon' rows and rows without a duration", () => {
  const rows = [
    {
      state: "published",
      reason: "",
      started_at: "2026-10-19T10:00:00.000Z",
      duration_sec: 5,
    },
    {
      state: "skipped_existing",
      reason: "haben wir schon",
      started_at: "2026-10-19T10:00:00.000Z",
      duration_sec: 0,
    },
    {
      state: "already_listed",
      reason: "haben wir schon",
      started_at: "2026-10-19T10:00:00.000Z",
      duration_sec: 0,
    },
    {
      state: "queued",
      reason: "",
      started_at: "",
      duration_sec: null,
    },
    {
      state: "rejected",
      reason: "no_asin",
      started_at: "",
      duration_sec: null,
    },
    {
      state: "error",
      reason: "boom",
      started_at: "2026-10-19T10:00:00.000Z",
      duration_sec: 7,
    },
  ];

  const stats = uploadDurationStats(rows, 0, false);

  assert.equal(stats.processed, 2);
  assert.equal(stats.totalSec, 12);
  assert.equal(stats.averageSec, 6);
});

test("a skipped row's reason alone is enough to exclude it", () => {
  const stats = uploadDurationStats(
    [
      {
        state: "published",
        reason: "haben wir schon",
        started_at: "2026-10-19T10:00:00.000Z",
        duration_sec: 1,
      },
      {
        state: "published",
        reason: "",
        started_at: "2026-10-19T10:00:00.000Z",
        duration_sec: 5,
      },
    ],
    0,
    false,
  );

  assert.equal(stats.processed, 1);
  assert.equal(stats.totalSec, 5);
  assert.equal(stats.averageSec, 5);
});

test("the running row ticks only while the run is live", () => {
  const row = {
    state: "fetching",
    reason: "",
    started_at: "2026-10-19T10:00:00.000Z",
    duration_sec: null,
  };

  assert.equal(rowDurationSeconds(row, Date.parse(row.started_at) + 4000, true), 4);
  assert.equal(rowDurationSeconds(row, Date.parse(row.started_at) + 4000, false), null);
});

test("run rows are shown only for the selected file", () => {
  assert.equal(runRowsMatchSelectedFile(true, "upload-1", "a.txt", "a.txt"), true);
  assert.equal(runRowsMatchSelectedFile(true, "upload-1", "a.txt", "b.txt"), false);
  assert.equal(runRowsMatchSelectedFile(false, "upload-1", "a.txt", "a.txt"), false);
  assert.equal(runRowsMatchSelectedFile(true, "", "a.txt", "a.txt"), false);
  assert.equal(runRowsMatchSelectedFile(true, "upload-1", "", ""), false);
});

test("preview waits for the file listing and a surviving selection", () => {
  const listing = {
    default: "a.txt",
    files: [{ name: "a.txt" }, { name: "b.txt" }],
  };

  // A remembered file must not be previewed before /files answers.
  assert.equal(previewFileToLoad(null, "gone.txt"), null);
  // Once the listing arrives, a missing remembered file waits for fallback.
  assert.equal(previewFileToLoad(listing, "gone.txt"), null);
  assert.equal(previewFileToLoad(listing, ""), null);
  assert.equal(previewFileToLoad(listing, "b.txt"), "b.txt");
});
