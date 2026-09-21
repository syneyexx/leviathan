export type FinalBetaChatThread = {
  id: string;
  title: string;
  preview: string;
  when: string;
};

export const mockChatThreads: FinalBetaChatThread[] = [
  { id: "c1", title: "HADES BETA uitwerken", preview: "Werk de navigatie van HADES ...", when: "10:24" },
  { id: "c2", title: "Research samenvatten", preview: "Belangrijkste inzichten uit de ...", when: "09:12" },
  { id: "c3", title: "Plugin instellen", preview: "Stappen voor lokale installatie", when: "14 apr" },
];

export const mockChatMessages = [
  { id: "m1", role: "user" as const, author: "Romy", time: "10:23", text: "Werk de navigatie van HADES verder uit." },
  {
    id: "m2",
    role: "assistant" as const,
    author: "HADES",
    time: "10:24",
    text: "Ik groepeer de werkruimtes in Werk, Kennis en Systeem.",
  },
];
