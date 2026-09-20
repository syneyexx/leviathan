export type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type Message = {
  id: number;
  conversation_id: string;
  role: "system" | "user" | "assistant";
  content: string;
  created_at: string;
};

export type ReasoningSummary = {
  intent: string;
  complexity: string;
  use_knowledge: boolean;
  steps: string[];
};

export type KnowledgeSource = {
  id: string;
  title: string;
  source: string;
};

export type ChatResponse = {
  conversation_id: string;
  user_message: Message;
  assistant_message: Message;
  model: string;
  reasoning: ReasoningSummary;
  knowledge_sources: KnowledgeSource[];
};

export type HealthResponse = {
  ok: boolean;
  version: string;
  database: string;
  reasoning_enabled: boolean;
  llm: {
    available: boolean;
    model: string | null;
    base_url: string;
    error?: string;
  };
};

export type ApiErrorBody = {
  detail?: string | { msg: string }[];
};
