# Sprint 3 risk acceptance (D2 = accepted)

Recorded 2026-11-10 from the operator's chat answer ("1. (automatisch ist das was wir gerade wollen)").

Accepted by the operator: an automated Chrome (own profile, off-screen) operates the eBay web listing form on account butterflypro, including drafts
and, for the single D4 item B0D87HWM4W only, one live submit after typed `LIVE 1`.
Known and not measurable or reversible: eBay's user agreement restricts automated access; the account is already restricted (errorId 25019); the robot
may cause a further restriction of the account. The LIVE 1 gate protects against accidents, not against this risk.
Stop rules stay: captcha, unexpected page, lost session, any read-back mismatch, any unlisted click = the run stops; no bot-detection bypass; no headless mode.
