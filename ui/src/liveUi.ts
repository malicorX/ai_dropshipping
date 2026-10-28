/**
 * Pure UI logic for the guarded live path.  Kept free of React so the rules
 * can be unit-tested with node:test.
 */

export const LEGACY_LIVE_DISABLED_REASON =
  "Disabled in production — use the Prepared tab or the guarded upload plan.";

/** The old single-listing stage/publish endpoints only work on sandbox. */
export function legacyListingDisabled(env: string | undefined): boolean {
  return env === "production";
}

/**
 * The PRODUCTION banner is driven by the shared run status: any live run, in
 * either mode, is visible on both the Upload and Prepared tabs.
 */
export function liveBannerVisible(
  status: { live?: boolean } | null | undefined,
): boolean {
  return !!status?.live;
}

/** Every live start/plan confirmation must echo the server's plan nonce. */
export function withPlanNonce(
  plan: { nonce?: string },
  payload: Record<string, unknown>,
): Record<string, unknown> {
  return { ...payload, plan_nonce: plan.nonce ?? "" };
}

export type LiveRunStatus = {
  running?: boolean;
  live?: boolean;
  mode?: string;
};
