/** Chat chrome strings for NL/EN settings.language (Wave 22). Dynamic content stays untouched. */
export type ChatLang = "nl" | "en";

const COPY = {
  nl: {
    newChat: "Nieuw gesprek",
    send: "Versturen",
    cancel: "Annuleren",
    branchHere: "Branch here",
    systemPrompt: "System prompt",
    branches: "Vertakkingen",
    provenance: "Bronnen",
    attach: "Bijlage",
    placeholder: "Vraag stellen, /help, /harvest <url>, @memory:… of sleep bestanden…",
    pendingApproval: "Blokkering: openstaande goedkeuring",
  },
  en: {
    newChat: "New chat",
    send: "Send",
    cancel: "Cancel",
    branchHere: "Branch here",
    systemPrompt: "System prompt",
    branches: "Branches",
    provenance: "Sources",
    attach: "Attachment",
    placeholder: "Ask anything, /help, /harvest <url>, @memory:… or drop files…",
    pendingApproval: "Blocked: pending approval",
  },
} as const;

export function chatChrome(lang: ChatLang | string | undefined) {
  return COPY[lang === "en" ? "en" : "nl"];
}
