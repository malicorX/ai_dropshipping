import assert from "node:assert/strict";
import test from "node:test";

import {
  LEGACY_LIVE_DISABLED_REASON,
  legacyListingDisabled,
  liveBannerVisible,
  withPlanNonce,
} from "../.test-build/liveUi.js";

test("legacy List on eBay is disabled only in production", () => {
  assert.equal(legacyListingDisabled("production"), true);
  assert.equal(legacyListingDisabled("sandbox"), false);
  assert.equal(legacyListingDisabled(undefined), false);
  assert.match(LEGACY_LIVE_DISABLED_REASON, /Prepared tab/);
});

test("the live banner follows the shared run status in any mode", () => {
  assert.equal(liveBannerVisible({ live: true, mode: "full" }), true);
  assert.equal(liveBannerVisible({ live: true, mode: "publish" }), true);
  assert.equal(liveBannerVisible({ live: false, mode: "full" }), false);
  assert.equal(liveBannerVisible(null), false);
  assert.equal(liveBannerVisible(undefined), false);
});

test("every live confirmation echoes the server plan nonce", () => {
  const body = withPlanNonce(
    { nonce: "abc123" },
    { confirm: "LIVE 2", batch_hash: "h" },
  );
  assert.equal(body.plan_nonce, "abc123");
  assert.equal(body.confirm, "LIVE 2");
  assert.equal(body.batch_hash, "h");
});
