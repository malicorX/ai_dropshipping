<!-- disposition: decision-doc -->
# Sprint 1 planning consolidation - 2026-10-13

Brief: `.ai-briefs/sprint1-plan-round1-2026-10-13.md` (commit 0392ba1). Session `sprint1-dropshipping-plan`.
First dispatch (8 jobs) failed before any seat ran: the driver's job files had `\a` in the path turned into a bell character by the shell. Resubmitted as `-r2-`.

## Roster
Available and used: codex, gpt61-sol, gpt6-luna-max, opus, deepcode, deepseek, nv-nemotron. Dispatched but failed: nv-glm (empty backend response; no vote, not counted). Skipped: kimi, grok (quota), mimo-* (balance 0), qwen38-flash-next (unreachable), Fable (banned by operator). Families: OpenAI x3, Anthropic, DeepSeek x2, NVIDIA.

## Correction to my own brief
The brief said nothing was found that checks for an existing eBay offer. opus found `ebay/listing.py` already builds SKU `DD-<ASIN>` (listing.py:17), and `publish_offer` looks the offer up by SKU (listing.py:225-240). I confirmed lines 17, 200, 225 and 236-240. Its gaps, per opus (read at 0392ba1), are: it trusts local state, and `_offer_id_for_sku` treats HTTP 400 as "no offer". Not yet confirmed by running anything.

## Second finding (deepcode)
Seats read the repo at committed HEAD, so none of them saw the 24 dirty files (variation_expand.py, bulk/ etc.). Review of that code is impossible until it is committed. Hence T1 comes first.

## Convergence (7 of 7 answering seats)
- The draft bar "20 of 25 published" mixes throughput with the reject cohort and is incoherent once duplicates and margin-FAILs are seeded.
- Fix: define E = expected unique, margin-PASS target ASINs; denominators and the sample's expected per-row outcome are frozen in T0 before any run.
- Margin-FAIL and a correctly rejected duplicate are correct dispositions, never publications.
- Dedup must be proven against eBay sandbox state, not only the local DB; the re-run must create zero new offers/items.
- A dedup card is mandatory; "duplicate" is split into: URL forms -> same ASIN; ASIN already in DB; SKU/offer/item already on eBay; sibling and shared-child ASINs; near-identical titles.
- The live-write guard must be tested with a refusal (negative test), and the artifact must show the eBay host.
- Builder never reviews; critic from another family.

## Decisions
1. **Operator decision (2026-10-13): one eBay listing per ASIN.** Variation-group publishing is out of Sprint 1 (backlog). Sibling ASINs stay distinct; a child reachable from two parents appears once.
2. Near-identical titles on distinct ASINs: **flagged for review, never auto-merged or auto-skipped** (codex, sol, luna). nv-nemotron's "only first published" (Levenshtein <= 3) is rejected: it silently drops a valid per-ASIN listing. opus wanted it dropped entirely as unfalsifiable; the flag is kept because it is cheap and checkable (a flag row exists), but it is not part of the bar.
3. Bar (registered in T0, text below). Threshold 80% of E (opus asked 90%, deepcode/sol 80%); 80% wins, 4 of 5 stated it. nv-nemotron's 13/13 is rejected as it fixes E to its own sample composition.
4. Sample: 25 rows seeded from bulk/000001.txt with a seed recorded in T0: >=15 distinct expected margin-PASS targets (E), including a sibling pair and a shared-child case; 2 URL aliases of one ASIN; 1 exact repeat; 1 junk URL; 2 margin-FAILs; 1 DB-only candidate (eligible, in E); 1 pre-existing sandbox offer/item (baseline, reused, not a new publication). Exact counts fixed in T0; if E < 10 the sprint result is INCONCLUSIVE.
5. Drafted cards were re-cut: see plan issue #13.

## Registered bar (text for the goal issue)
MET iff all of: every one of the 25 rows ends in exactly one registered terminal state with the registered reason; at least ceil(0.8*|E|) targets in E reach a published sandbox item; after the identical second run, the count of offers and items per SKU read from the eBay sandbox API is unchanged and exactly one per identity; zero requests to production eBay hosts (logged); zero Amazon purchases; zero live writes. WEAK: 60-79% of E with all safety conditions true. NOT_MET otherwise. INCONCLUSIVE: |E| < 10, an unregistered change to sample/code between registration and run, or a dedup claim backed only by local files or mocks.
Failure even if all cards are Done: sample or denominator changed after seeing results; guard asserted but never exercised; dedup proven on an empty DB only; reviewer unable to reproduce the sandbox IDs.

## Dissent kept open
- opus: per-family dedup (D3) settles a product question; resolved by the operator (per ASIN).
- deepcode: a sandbox bar does not exercise production SKU uniqueness. Accepted and stated as not claimed.
- codex/sol: remote idempotency may exceed one week. Mitigation: the dedup card is sized M with a pre-agreed cut line (see plan #13).

## Seats and roles (proposed; voted next)
Planner/driver/integrator: this session. Builder: codex (OpenAI). Tester: deepcode (DeepSeek, tool loop, runs the sample). Reviewer: opus (Anthropic). Critic: deepseek (DeepSeek chat; reads evidence receipts). Standing note: codex, gpt61-sol and luna share a family; sol and luna are fallback only, never reviewer of codex's work.

## First task
T0, registration. Falsifier (all seats): a feasible, unambiguous E of at least 10 cannot be built from bulk/000001.txt, or the sandbox cannot be queried by SKU.
