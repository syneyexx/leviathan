# Autonomous Media Intelligence — continuation state

- **current branch:** `feature/autonomous-media-intelligence`
- **base SHA:** `0842b2a2dcf29fdb8e6197b0f91bcc579ac02600` (`origin/main`)
- **HEAD:** see `git log -1`
- **PR:** https://github.com/syneyexx/HADES/pull/102 (draft, not merged)
- **completed phases:** domain core, orchestrator, adapters, API, MEDIA page, tests, docs, PR
- **active phase:** awaiting tomorrow human review / external OAuth setup
- **working capabilities:** channel/project lifecycle; trend→render pipeline; FFmpeg render; publish durability/consent; capability doctor; Media page
- **tests actually executed:** `tests.test_media_intelligence` 18 passed; FFmpeg probe verified; `npm run typecheck` passed
- **setup still required:** user OAuth apps/credentials; optional ComfyUI/VoiceStudio
- **external blockers:** live platform OAuth (user-owned)
- **next exact action:** Strijder reviews PR #102 + MEDIA_SETUP_REQUIRED.md

## Verified platform API assumptions (2026-09-14)

- TikTok CPA creator_info + Direct Post; unaudited SELF_ONLY
- YouTube Data API v3 resumable videos.insert
- Instagram Graph v26 Reels container publish; Instagram Login scopes
- Facebook Page video_reels v26 start/finish; PAGE_REQUIRED
