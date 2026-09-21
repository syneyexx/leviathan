# HADES agent instructions

HADES is an offline-first Windows local AI workspace. The active engineering
direction is **Chat-primary HADES-10 product completion**: finish end-to-end
user workflows through Chat while keeping Advanced capability consoles available.

The user decides what should be built, fixed or improved; do not autonomously
follow a predefined development plan or archived Gen2 backlog. Preserve verified
behavior and the current visual identity unless the task explicitly changes them
(D003 GUI freeze is lifted only for Chat-primary information architecture).

Work subsystem-first, use `docs/HADES_CODEBASE_MAP.md` for the minimal relevant
read-set, and obey the matching scoped `.cursor/rules`. Never fake success:
verify lifecycle, persistence, output and tests where relevant. Keep `main`
releasable and update `docs/CURRENT_STATUS.md` after substantial verified changes.

Archived Gen1 vision and Gen2 planning live under `docs/archive/` — historical
evidence only, not open backlog. Do not create replacement roadmaps.
