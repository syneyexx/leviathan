# LEVIATHAN — Standalone browser shell

Fluid HTML/CSS/JS recreation of the LEVIATHAN Command + Chat layouts.

## Open

Serve the folder (recommended) or open pages directly:

```bash
python -m http.server 8765 --directory LEVIATHAN
```

Then open:

- Command: `http://localhost:8765/`
- Chat: `http://localhost:8765/chat.html`

## Notes

- Design tokens live in `css/tokens.css` (canonical visual system).
- Layout scales with the browser via `clamp()`, fluid grid columns, and responsive breakpoints.
- No backend is bundled; controls are visual/demo interactions with exact mock data from the references.
