# Media Platforms

Verified against official docs on **2026-09-14**.

## TikTok — Content Posting API

- `POST /v2/post/publish/creator_info/query/` before Direct Post
- Honor `privacy_level_options` (no silent public default)
- Unaudited clients → `PRIVATE_ONLY` / `SELF_ONLY` only
- FILE_UPLOAD / PULL_FROM_URL; creator consent → `WAITING_PLATFORM_CONSENT`
- Docs: https://developers.tiktok.com/doc/content-posting-api-get-started (updated 2026-08-04)

## YouTube — Data API v3

- OAuth + `videos.insert` resumable upload
- `snippet` + `status.privacyStatus` + `selfDeclaredMadeForKids`
- Shorts vs long are format variants; do not invent fragile Shorts heuristics

## Instagram — Graph v26.0

- Container `media_type=REELS` → poll `status_code` → `media_publish`
- Instagram Login scopes: `instagram_business_basic`, `instagram_business_content_publish`, …
- Facebook Page not required for Instagram Login path
- App Review often required for production publish → `APP_REVIEW_REQUIRED`

## Facebook — Page Reels Graph v26.0

- `/{page-id}/video_reels` `upload_phase=start|finish`
- Page access token + `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`
- Personal profile publishing unsupported → `PAGE_REQUIRED` / `PLATFORM_LIMITATION`

## Shared Meta auth

`media/platforms/meta_auth.py` — tokens via HADES secret store only; never logs/tokens in API payloads.
