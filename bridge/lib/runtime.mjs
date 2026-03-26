import { Codex } from "@openai/codex-sdk";
import { createOpencode } from "@opencode-ai/sdk";

let codexClient = null;
let opencodePromise = null;

export function combinePrompts(systemPrompt, prompt) {
  if (!systemPrompt) {
    return prompt;
  }
  return [
    "# System Instructions",
    systemPrompt.trim(),
    "",
    "# User Request",
    prompt.trim(),
  ].join("\n");
}

export function extractTextParts(parts) {
  if (!Array.isArray(parts)) {
    return "";
  }
  const chunks = [];
  for (const part of parts) {
    if (!part || typeof part !== "object") {
      continue;
    }
    if (typeof part.text === "string") {
      chunks.push(part.text);
      continue;
    }
    if (Array.isArray(part.parts)) {
      const nested = extractTextParts(part.parts);
      if (nested) {
        chunks.push(nested);
      }
    }
  }
  return chunks.join("\n").trim();
}

export function buildCodexTurnOptions(outputSchema) {
  return outputSchema ? { outputSchema } : undefined;
}

function getCodexClient() {
  if (!codexClient) {
    codexClient = new Codex();
  }
  return codexClient;
}

async function getOpencodeInstance() {
  if (!opencodePromise) {
    opencodePromise = createOpencode();
  }
  return opencodePromise;
}

function parseModelIdentifier(model) {
  if (!model || typeof model !== "string" || !model.includes("/")) {
    return null;
  }
  const [providerID, ...rest] = model.split("/");
  const modelID = rest.join("/");
  if (!providerID || !modelID) {
    return null;
  }
  return { providerID, modelID };
}

export function buildOpencodePromptBody(params) {
  const body = {
    parts: [{ type: "text", text: params.prompt }],
    noReply: false,
  };
  if (params.systemPrompt) {
    body.system = params.systemPrompt;
  }
  if (params.outputSchema) {
    body.format = {
      type: "json_schema",
      schema: params.outputSchema,
    };
  }
  const model = parseModelIdentifier(params.model);
  if (model) {
    body.model = model;
  }
  return body;
}

export function ensureOpencodeProviders(providersPayload) {
  const providerList = providersPayload?.data?.providers || [];
  if (!providerList.length) {
    throw new Error(
      "No OpenCode providers configured. Run `opencode providers login` first."
    );
  }
  return providerList;
}

export async function runCodex(params) {
  const codex = getCodexClient();
  const thread = codex.startThread({
    workingDirectory: params.cwd,
    skipGitRepoCheck: params.skipGitRepoCheck ?? true,
    sandboxMode: params.sandboxMode ?? "workspace-write",
    approvalPolicy: params.approvalPolicy ?? "never",
    model: params.model || undefined,
    modelReasoningEffort: params.reasoningEffort || undefined,
    networkAccessEnabled: params.networkAccessEnabled ?? true,
    additionalDirectories: params.additionalDirectories || undefined,
  });

  const input = combinePrompts(params.systemPrompt, params.prompt);
  const turnOptions = buildCodexTurnOptions(params.outputSchema);
  const turn = await thread.run(input, turnOptions);

  return {
    runtime: "codex",
    finalText: turn.finalResponse || "",
    items: turn.items || [],
    usage: turn.usage || null,
    threadId: thread.id,
  };
}

export async function runOpencode(params) {
  const { client } = await getOpencodeInstance();
  const providers = await client.config.providers();
  ensureOpencodeProviders(providers);

  const session = await client.session.create({
    query: { directory: params.cwd },
    body: { title: params.title || "claude-code-tunnels" },
  });
  const sessionId = session?.data?.id;
  if (!sessionId) {
    throw new Error("OpenCode session creation did not return an id.");
  }

  const body = buildOpencodePromptBody(params);

  const result = await client.session.prompt({
    query: { directory: params.cwd },
    path: { id: sessionId },
    body,
  });

  const info = result?.data?.info || {};
  const parts = result?.data?.parts || [];
  const structured = info.structured_output;
  const finalText =
    structured !== undefined
      ? JSON.stringify(structured)
      : extractTextParts(parts) || info.text || "";

  return {
    runtime: "opencode",
    finalText,
    info,
    parts,
    sessionId,
    structuredOutput: structured ?? null,
  };
}

export async function bridgeHealth() {
  const { client } = await getOpencodeInstance();
  const providers = await client.config.providers();
  return {
    runtimes: ["codex", "opencode"],
    opencodeProviders: providers?.data?.providers?.length || 0,
  };
}

export async function closeBridgeResources() {
  if (opencodePromise) {
    const { server } = await opencodePromise;
    server.close();
    opencodePromise = null;
  }
}
