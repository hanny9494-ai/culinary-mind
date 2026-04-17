/**
 * inference.ts
 * Thin wrapper around the VS Code Language Model API.
 * Resolves a model by vendor/family, sends a chat request, and returns
 * either the full text or an async generator of chunks for streaming.
 */

import * as vscode from 'vscode';

export interface ModelSelector {
  vendor?: string;
  family?: string;
}

export interface InferenceOptions {
  prompt: string;
  system?: string;
  selector: ModelSelector;
  timeoutMs: number;
}

export interface InferenceResult {
  text: string;
  model: string;
  usage?: {
    promptTokens?: number;
    completionTokens?: number;
  };
}

/** Pick the best matching model. Returns null if none found. */
export async function resolveModel(
  selector: ModelSelector
): Promise<vscode.LanguageModelChat | null> {
  const filter: vscode.LanguageModelChatSelector = {};
  if (selector.vendor) { filter.vendor = selector.vendor; }
  if (selector.family) { filter.family = selector.family; }

  let models = await vscode.lm.selectChatModels(filter);

  // If nothing found with the specific filter, fall back to any available model
  if (models.length === 0 && (selector.vendor || selector.family)) {
    models = await vscode.lm.selectChatModels({});
  }

  return models.length > 0 ? models[0] : null;
}

/** Build the message array, prepending a system turn if provided. */
function buildMessages(
  prompt: string,
  system?: string
): vscode.LanguageModelChatMessage[] {
  const messages: vscode.LanguageModelChatMessage[] = [];
  if (system) {
    // VS Code LM API: use Assistant role for system-like context on models
    // that don't have a dedicated system role.
    messages.push(vscode.LanguageModelChatMessage.Assistant(system));
  }
  messages.push(vscode.LanguageModelChatMessage.User(prompt));
  return messages;
}

/**
 * Run a non-streaming inference request.
 * Throws on timeout, model unavailability, or API error.
 */
export async function runInference(
  options: InferenceOptions
): Promise<InferenceResult> {
  const model = await resolveModel(options.selector);
  if (!model) {
    const err = new Error(
      `No model available for vendor="${options.selector.vendor}" family="${options.selector.family}"`
    );
    (err as NodeJS.ErrnoException).code = 'MODEL_NOT_FOUND';
    throw err;
  }

  const messages = buildMessages(options.prompt, options.system);
  const cancelSource = new vscode.CancellationTokenSource();

  const timeoutHandle = setTimeout(() => {
    cancelSource.cancel();
  }, options.timeoutMs);

  try {
    const response = await model.sendRequest(
      messages,
      {},
      cancelSource.token
    );

    let text = '';
    for await (const chunk of response.text) {
      text += chunk;
    }

    // Usage may not be available on all model providers
    let usage: InferenceResult['usage'];
    try {
      const raw = response as unknown as {
        usage?: { promptTokens?: number; completionTokens?: number };
      };
      if (raw.usage) {
        usage = {
          promptTokens: raw.usage.promptTokens,
          completionTokens: raw.usage.completionTokens,
        };
      }
    } catch {
      // usage not available — ignore
    }

    return {
      text,
      model: `${model.vendor}/${model.family}`,
      usage,
    };
  } finally {
    clearTimeout(timeoutHandle);
    cancelSource.dispose();
  }
}

/**
 * Run a streaming inference request.
 * Returns an async generator yielding text chunks.
 * The caller is responsible for handling the cancellation token lifecycle.
 */
export async function* streamInference(
  options: InferenceOptions,
  cancelToken: vscode.CancellationToken
): AsyncGenerator<{ chunk?: string; done?: boolean; model?: string; error?: string }> {
  const model = await resolveModel(options.selector);
  if (!model) {
    yield {
      error: `No model available for vendor="${options.selector.vendor}" family="${options.selector.family}"`,
      done: true,
    };
    return;
  }

  const messages = buildMessages(options.prompt, options.system);

  try {
    const response = await model.sendRequest(messages, {}, cancelToken);
    for await (const chunk of response.text) {
      if (cancelToken.isCancellationRequested) { break; }
      yield { chunk };
    }
    yield { done: true, model: `${model.vendor}/${model.family}` };
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    yield { error: message, done: true };
  }
}
