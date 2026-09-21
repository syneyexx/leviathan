# MEDIA SETUP REQUIRED

User checklist for Autonomous Media Intelligence. **No secrets belong in this file.**

## REQUIRED SOFTWARE

- [ ] FFmpeg on PATH (`ffmpeg` / `ffmpeg.exe`)
- [ ] HADES model endpoint (LM Studio or configured gateway)
- [ ] Optional: faster-whisper for local ASR
- [ ] Optional: Piper / VoiceStudio for TTS
- [ ] Optional: ComfyUI for image generation

## YOUTUBE

- [ ] Google Cloud project
- [ ] YouTube Data API enabled
- [ ] OAuth client + channel authorization
- [ ] Confirm any API project verification / quota limits

## TIKTOK

- [ ] TikTok developer account + app
- [ ] Content Posting API + `video.publish`
- [ ] OAuth token for creator
- [ ] Client audit for unrestricted public Direct Post (until then: private/`SELF_ONLY` only)

## INSTAGRAM

- [ ] Meta developer app
- [ ] Instagram professional account (Business/Creator)
- [ ] Instagram Login (`instagram_business_*`) and/or Facebook Login path
- [ ] Meta App Review for production publishing permissions

## FACEBOOK

- [ ] Meta developer app
- [ ] Facebook Page with `CREATE_CONTENT`
- [ ] Page token scopes: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`
- [ ] App Review where required

## OPTIONAL LOCAL AI

- [ ] ComfyUI endpoint + workflow/model (HADES will not silently download huge models)
- [ ] Vision model id for frame analysis

## CURRENT DETECTION RESULTS

Open **Media → Setup** after starting HADES. The Capability Doctor writes live statuses (`READY`, `AUTH_REQUIRED`, `PRIVATE_ONLY`, `PAGE_REQUIRED`, …).

## HOW TO VERIFY

1. Create a channel with selected platforms.
2. Run **Produce once** (or set autonomy and scheduler tick).
3. Confirm master render under project artifacts when FFmpeg is installed.
4. Confirm publish jobs stay `AUTH_REQUIRED` / consent-waiting until real OAuth exists.
5. Never expect silent browser/password automation — official APIs only.
