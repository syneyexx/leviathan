/**
 * TEST-ONLY deterministic Screen 1 fixture for Chat V2 visual regression.
 * Activated solely via Playwright route mocking + window.__LV_V2_VISUAL_FIXTURE__.
 * Never import these values into production ChatPage defaults.
 */

export const CHAT_V2_VISUAL_FROZEN_ISO = "2025-05-25T14:37:26";

const CONV_ID = "conv-fixture-ai-infra";

export const CHAT_V2_VISUAL_FIXTURE = {
  health: {
    ok: true,
    version: "visual-fixture",
    database: "ok",
    reasoning_enabled: true,
    llm: { available: true, model: "Qwen2.5-14B-Instruct", base_url: "http://127.0.0.1:1234" },
    agents: { enabled: true },
    approvals: { pending: 0 },
    jobs: { queued: 2 },
    capabilities: { registered: 8 },
  },
  telemetry: {
    collectedAt: CHAT_V2_VISUAL_FROZEN_ISO,
    ageMs: 200,
    cpu: { available: true, utilizationPct: 32 },
    memory: {
      available: true,
      totalBytes: 16 * 1024 ** 3,
      usedBytes: 6.2 * 1024 ** 3,
      availableBytes: 9.8 * 1024 ** 3,
      utilizationPct: 61,
    },
    disk: {
      available: true,
      utilizationPct: 34,
      totalBytes: 500 * 1024 ** 3,
      usedBytes: 170 * 1024 ** 3,
      freeBytes: 330 * 1024 ** 3,
      metric: "capacity_utilization",
    },
    gpu: {
      available: true,
      devices: [
        {
          index: 0,
          name: "GTX 1060",
          utilizationPct: 54,
          vramTotalBytes: 6 * 1024 ** 3,
          vramUsedBytes: 1.2 * 1024 ** 3,
          vramFreeBytes: 4.8 * 1024 ** 3,
          vramUtilizationPct: 20,
          temperatureC: 58,
        },
        {
          index: 1,
          name: "RTX 5060 Ti",
          utilizationPct: 78,
          vramTotalBytes: 16 * 1024 ** 3,
          vramUsedBytes: 2.2 * 1024 ** 3,
          vramFreeBytes: 13.8 * 1024 ** 3,
          vramUtilizationPct: 14,
          temperatureC: 68,
        },
      ],
    },
    truth: { measured: true, synthetic: false, unavailableIsNotZero: true },
    dashboard: { cpuPct: 32, ramPct: 61, gpuPct: 78, vramPct: 15, diskPct: 34 },
  },
  models: {
    models: [
      {
        id: "qwen2.5-14b-instruct",
        displayName: "Qwen2.5-14B-Instruct",
        providerId: "lmstudio",
        source: "local",
        family: "Qwen",
        parameterCount: 14_000_000_000,
        quantization: "Q4_K_M",
        format: "GGUF",
        contextWindow: 32768,
        capabilities: {
          chat: "supported",
          reasoning: "supported",
          coding: "supported",
          toolCalling: "supported",
          structuredOutput: "supported",
          vision: "unsupported",
          embeddings: "unsupported",
          streaming: "supported",
        },
        lifecycleState: "ready",
        health: "ok",
        active: true,
        loaded: true,
      },
    ],
    status: { ready: true },
  },
  capabilities: {
    capabilities: [
      { id: "web.search", name: "Web Search", available: true, enabled: true },
      { id: "knowledge.rag", name: "RAG Retriever", available: true, enabled: true },
      { id: "python.interpreter", name: "Python Interpreter", available: true, enabled: true },
      { id: "data.analyze", name: "Data Analysis", available: true, enabled: true },
      { id: "web.fetch", name: "Web Fetch", available: true, enabled: true },
      { id: "knowledge.embed", name: "Embeddings", available: true, enabled: true },
      { id: "code.lint", name: "Code Lint", available: true, enabled: true },
      { id: "data.sql", name: "SQL Probe", available: true, enabled: true },
    ],
  },
  conversations: {
    conversations: [
      {
        id: CONV_ID,
        title: "AI infrastructuur strategie",
        created_at: "2025-05-25T09:10:00",
        updated_at: "2025-05-25T14:20:00",
        pinned: false,
      },
      {
        id: "conv-fixture-2",
        title: "GPU geheugen optimalisatie",
        created_at: "2025-05-25T08:00:00",
        updated_at: "2025-05-25T11:05:00",
        pinned: false,
      },
      {
        id: "conv-fixture-3",
        title: "LM Studio setup checklist",
        created_at: "2025-05-24T16:00:00",
        updated_at: "2025-05-24T18:30:00",
        pinned: false,
      },
      {
        id: "conv-fixture-4",
        title: "Qwen vs Llama vergelijking",
        created_at: "2025-05-20T10:00:00",
        updated_at: "2025-05-21T12:00:00",
        pinned: false,
      },
    ],
  },
  conversationDetail: {
    conversation: {
      id: CONV_ID,
      title: "AI infrastructuur strategie",
      created_at: "2025-05-25T09:10:00",
      updated_at: "2025-05-25T14:20:00",
      pinned: false,
    },
    messages: [
      {
        id: 1,
        conversation_id: CONV_ID,
        role: "user",
        content:
          "Kun je een plan maken voor het optimaliseren van mijn lokale AI setup?",
        created_at: "2025-05-25T14:15:00",
      },
      {
        id: 2,
        conversation_id: CONV_ID,
        role: "assistant",
        content:
          "**Analyse van je huidige setup**\n\n• GPU 0: GTX 1060 (6 GB) — inference / aux\n• GPU 1: RTX 5060 Ti (16 GB) — primary serving\n• Runtime: LM Studio + GGUF Qwen2.5-14B\n\n**Optimalisatieplan (overzicht)**\n\n1. Pin primary model op GPU 1 met Q4_K_M\n2. Beperk context window tot gemeten VRAM budget\n3. Schakel RAG alleen in bij knowledge intents\n4. Houd aux GPU vrij voor embeddings / light jobs\n5. Meet TTFT en tok/s na elke wijziging",
        created_at: "2025-05-25T14:15:23",
      },
    ],
  },
  memory: {
    memory: Array.from({ length: 24 }, (_, i) => ({
      id: `mem-${i + 1}`,
      status: "ACTIVE",
      kind: "note",
      content: `Fixture memory ${i + 1}`,
    })),
  },
  codingStatus: { enabled: true },
  /** Hydrated into ChatPage lastTurn when visual fixture is active (TEST ONLY). */
  uiState: {
    selectedModelId: "qwen2.5-14b-instruct",
    reasoningMode: "deep" as const,
    collaborationStrategy: "direct" as const,
    lastTurn: {
      model: "Qwen2.5-14B-Instruct",
      intent: "optimize_local_ai",
      complexity: "deep",
      knowledgeCount: 5,
      streaming: "complete" as const,
      reasoning: {
        intent: "optimize_local_ai",
        complexity: "deep",
        use_knowledge: true,
        steps: [
          "Inventariseer hardware en runtime constraints",
          "Meet huidige VRAM- en contextgebruik",
          "Prioriteer model-kwantizatie versus kwaliteit",
          "Scheid serving en hulptaken over GPU's",
          "Beperk retrieval tot benodigde bronnen",
          "Valideer latency en throughput",
          "Documenteer een herhaalbaar plan",
        ],
        mode: { requested: "deep", effective: "deep", source: "fixture" },
      },
      knowledgeSources: [
        {
          id: "src-1",
          title: "NVIDIA Runtime Docs",
          source: "https://docs.nvidia.com/cuda/",
        },
        {
          id: "src-2",
          title: "LM Studio Documentation",
          source: "https://lmstudio.ai/docs",
        },
        {
          id: "src-3",
          title: "Qwen2.5 Technical Report",
          source: "https://qwenlm.github.io/",
        },
        {
          id: "src-4",
          title: "GPU Memory Optimization",
          source: "https://developer.nvidia.com/blog/",
        },
        {
          id: "src-5",
          title: "Local LLM Performance Guide",
          source: "https://huggingface.co/docs",
        },
      ],
      cognitionMode: "deep",
      cognitionStatus: "COMPLETE",
      cognitionPhase: "Complete",
      language: "nl",
      languageSource: "fixture",
      reasoningMode: "deep",
      memoryCount: 24,
      verification: "Vertrouwd",
      telemetry: {
        model: "Qwen2.5-14B-Instruct",
        context_used: 8200,
        context_tokens: 8200,
        context_budget: 32768,
        knowledge_hits: 5,
        memory_hits: 24,
        evidence_hits: 0,
        latency_ms: 800,
        verification_mode: "REQUIRED",
        verification_passed: true,
        usage: { tokens_per_second: 25, output_tokens: 420 },
        truth: {
          telemetry_is_backend_backed: true,
          visual_fixture: true,
        },
      },
    },
  },
} as const;

export const CHAT_V2_ACTIVE_CONVERSATION_ID = CONV_ID;
