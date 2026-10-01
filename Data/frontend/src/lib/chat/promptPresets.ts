/**
 * Shared quick-prompt presets for Chat + PromptsPage.
 */

export type ChatPromptPreset = {
  label: string;
  text: string;
};

export const CHAT_PROMPT_PRESETS: readonly ChatPromptPreset[] = [
  {
    label: "Deep Research",
    text: "Research this topic deeply and structure the important questions first: ",
  },
  {
    label: "Analyze Data",
    text: "Analyze the following data and explain the important patterns: ",
  },
  {
    label: "Generate Code",
    text: "Help me design and implement the following code: ",
  },
  {
    label: "Create Plan",
    text: "Create a concrete step-by-step plan for: ",
  },
] as const;
