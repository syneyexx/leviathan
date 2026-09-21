---
name: hades-usage
description: How HADES uses this plugin (skills, tools, Chat). Claude Code / Codex CLIs are not required.
---

# Use this plugin in HADES

HADES is a local Windows AI workspace. Ignore Claude Code, Codex, Cursor, or Cowork installer steps.

1. Enable the plugin on the Plugins page when status is Ready.
2. Load guidance with `list_skills`, `search_skills`, and `get_skill`.
3. Run the plugin's tools from Chat or Plugins. Model ids for LM Studio are always caller-supplied — never hardcode a production model.
4. If a tool needs git, ffmpeg, or LM Studio and it is missing, trust the fail-closed error. Do not invent results.
5. Internet is optional. Stay on local files and local LM Studio unless the operator configured extra OpenAI-compatible URLs.
