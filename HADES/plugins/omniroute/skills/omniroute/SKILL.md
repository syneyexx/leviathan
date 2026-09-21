---
name: omniroute
description: OmniRoute (local-first)
---

# OmniRoute (local-first)

Default to HADES LM Studio (127.0.0.1:1234).

Extra providers only if HADES_EXTRA_LLM_BASE_URLS is set.
Never require internet. Model ids stay dynamic.
If a remote route fails, stay on local.
Coding may optionally execute through OmniRoute when the user enables the Coding toggle and this plugin is Ready. HADES chooses eligible routes in code; do not dump the catalog into prompts.
