import type {
  TavoApi,
  TavoChat,
  TavoCharacter,
  TavoGenerateOptions,
  TavoId,
  TavoIdLike,
  TavoLorebook,
  TavoMatchMode,
  TavoMemory,
  TavoMessage,
  TavoMessageFilter,
  TavoMessageIndexRange,
  TavoPersona,
  TavoPreset,
  TavoRegex,
  TavoResourceApi,
  TavoScope,
  TavoSelectOption
} from "./types.js";

type Named = { id?: TavoId; name: string };

export interface MockTavoOptions {
  variables?: Partial<Record<TavoScope, Record<string, unknown>>>;
  messages?: TavoMessage[];
  currentMessageId?: TavoId | null;
  chat?: Partial<TavoChat> | null;
  characters?: TavoCharacter[];
  personas?: TavoPersona[];
  presets?: TavoPreset[];
  lorebooks?: TavoLorebook[];
  regexes?: TavoRegex[];
  memory?: TavoMemory | null;
  input?: string;
  appVersion?: string;
  appVersionNumber?: number;
  select?: string | null | ((options: string[] | TavoSelectOption[], title?: string, defaultValue?: string) => string | null | Promise<string | null>);
  generate?: (prompt: string, options?: TavoGenerateOptions, runtime?: MockTavoRuntime) => string | null | Promise<string | null>;
}

export interface MockTavoRuntime {
  tavo: TavoApi;
  events: Array<{ type: string; payload: unknown }>;
  exports: Array<{ name: string; data: string }>;
  sentInputs: string[];
  toasts: string[];
  openedUrls: string[];
  state: {
    variables: Record<TavoScope, Record<string, unknown>>;
    input: string;
    messages: TavoMessage[];
    currentMessageId: TavoId | null;
    chat: TavoChat | null;
    memory: TavoMemory | null;
  };
}

function clone<T>(value: T): T {
  return value == null ? value : structuredClone(value);
}

function normalizeId(value: TavoIdLike): TavoId {
  return typeof value === "object" ? value.id : value;
}

function splitPath(path: string): string[] {
  return path.split(".").map((part) => part.trim()).filter(Boolean);
}

function readPath(source: Record<string, unknown>, path: string): unknown {
  let cursor: unknown = source;
  for (const part of splitPath(path)) {
    if (cursor == null || typeof cursor !== "object") return undefined;
    cursor = (cursor as Record<string, unknown>)[part];
  }
  return cursor;
}

function writePath(source: Record<string, unknown>, path: string, value: unknown): void {
  const parts = splitPath(path);
  if (parts.length === 0) return;
  let cursor = source;
  for (const part of parts.slice(0, -1)) {
    if (cursor[part] == null || typeof cursor[part] !== "object") cursor[part] = {};
    cursor = cursor[part] as Record<string, unknown>;
  }
  cursor[parts[parts.length - 1]!] = clone(value);
}

function deletePath(source: Record<string, unknown>, path: string): void {
  const parts = splitPath(path);
  if (parts.length === 0) return;
  let cursor: unknown = source;
  for (const part of parts.slice(0, -1)) {
    if (cursor == null || typeof cursor !== "object") return;
    cursor = (cursor as Record<string, unknown>)[part];
  }
  if (cursor && typeof cursor === "object") delete (cursor as Record<string, unknown>)[parts[parts.length - 1]!];
}

function matchesName(value: string, target: string, mode: TavoMatchMode = "exact"): boolean {
  if (mode === "prefix") return value.startsWith(target);
  if (mode === "suffix") return value.endsWith(target);
  if (mode === "contains") return value.includes(target);
  return value === target;
}

function nextNumericId(values: Array<{ id?: TavoId }>, fallback = 1): number {
  const nums = values.map((value) => typeof value.id === "number" ? value.id : Number.NaN).filter(Number.isFinite);
  return nums.length ? Math.max(...nums) + 1 : fallback;
}

class Store<T extends Named> implements TavoResourceApi<T> {
  private seq: number;
  private values = new Map<TavoId, T>();

  constructor(private readonly prefix: string, initial: T[] = []) {
    this.seq = nextNumericId(initial);
    for (const value of initial) {
      const next = clone(value);
      next.id = next.id ?? this.nextId();
      this.values.set(next.id, next);
    }
  }

  async all(): Promise<T[]> {
    return [...this.values.values()].map(clone);
  }

  async get(id: TavoIdLike): Promise<T | null> {
    return clone(this.values.get(normalizeId(id)) ?? null);
  }

  async find(name: string, options?: { match?: TavoMatchMode }): Promise<T | null> {
    for (const value of this.values.values()) {
      if (matchesName(value.name, name, options?.match)) return clone(value);
    }
    return null;
  }

  async create(value: T): Promise<T> {
    const next = clone(value);
    next.id = next.id ?? this.nextId();
    this.values.set(next.id, next);
    return clone(next);
  }

  async update(value: T & { id: TavoId }): Promise<T> {
    if (!this.values.has(value.id)) throw new Error(`${this.prefix} ${String(value.id)} does not exist`);
    const next = clone(value);
    this.values.set(value.id, next);
    return clone(next);
  }

  async delete(value: TavoIdLike): Promise<boolean> {
    return this.values.delete(normalizeId(value));
  }

  private nextId(): TavoId {
    return `${this.prefix}-${this.seq++}`;
  }
}

function resourceApi<T extends Named>(store: Store<T>): TavoResourceApi<T> {
  return {
    all: () => store.all(),
    get: (id) => store.get(id),
    find: (name, options) => store.find(name, options),
    create: (value) => store.create(value),
    update: (value) => store.update(value),
    delete: (value) => store.delete(value)
  };
}

function resolveIndex(index: number, length: number): number {
  return index < 0 ? length + index : index;
}

function rangeMessages(messages: TavoMessage[], range: TavoMessageIndexRange): TavoMessage[] {
  if (range == null || Array.isArray(range) && range.length === 0) return messages;
  if (typeof range === "number") {
    const index = resolveIndex(range, messages.length);
    return messages[index] ? [messages[index]!] : [];
  }
  const start = range[0] == null ? 0 : resolveIndex(range[0], messages.length);
  const end = range[1] == null ? messages.length - 1 : resolveIndex(range[1], messages.length);
  return messages.slice(Math.max(0, start), Math.min(messages.length, end + 1));
}

function messageMatches(message: TavoMessage, filter?: TavoMessageFilter): boolean {
  if (!filter) return true;
  if (filter.role !== undefined && message.role !== filter.role) return false;
  if (filter.hidden !== undefined && Boolean(message.hidden) !== filter.hidden) return false;
  if (filter.characters?.length) {
    const ids = new Set(filter.characters.map(normalizeId));
    if (message.characterId === undefined || !ids.has(message.characterId)) return false;
  }
  return true;
}

function seedChat(options: MockTavoOptions): TavoChat | null {
  if (options.chat === null) return null;
  return {
    id: "mock-chat-1",
    name: "Mock Chat",
    characters: options.characters ?? [],
    persona: options.personas?.[0] ?? null,
    lorebooks: options.lorebooks ?? [],
    regexes: options.regexes ?? [],
    ...options.chat
  };
}

export function createMockTavo(options: MockTavoOptions = {}): MockTavoRuntime {
  const variables: Record<TavoScope, Record<string, unknown>> = {
    chat: clone(options.variables?.chat ?? {}),
    global: clone(options.variables?.global ?? {})
  };
  const events: MockTavoRuntime["events"] = [];
  const exports: MockTavoRuntime["exports"] = [];
  const sentInputs: string[] = [];
  const toasts: string[] = [];
  const openedUrls: string[] = [];
  const messages: TavoMessage[] = clone(options.messages ?? []);
  let messageSeq = nextNumericId(messages);
  let currentMessageId = options.currentMessageId ?? messages.at(-1)?.id ?? null;
  let chat = clone(seedChat(options));
  let memory = clone(options.memory ?? {
    id: "mock-memory-1",
    enabled: false,
    memories: []
  } satisfies TavoMemory);
  const state = {
    variables,
    input: options.input ?? "",
    messages,
    currentMessageId,
    chat,
    memory
  };

  const character = new Store<TavoCharacter>("character", options.characters);
  const persona = new Store<TavoPersona>("persona", options.personas);
  const preset = new Store<TavoPreset>("preset", options.presets);
  const lorebook = new Store<TavoLorebook>("lorebook", options.lorebooks);
  const regex = new Store<TavoRegex>("regex", options.regexes);
  const characterApi = resourceApi(character);
  const personaApi = resourceApi(persona);
  const presetApi = resourceApi(preset);
  const lorebookApi = resourceApi(lorebook);
  const regexApi = resourceApi(regex);

  const bucket = (scope: TavoScope = "chat") => variables[scope];

  async function appendMessage(message: Partial<TavoMessage> & { role: "assistant" | "user"; content: string }): Promise<TavoId | null> {
    const id = message.id ?? messageSeq++;
    const { role, content, ...rest } = clone(message);
    const next: TavoMessage = {
      ...rest,
      id,
      role,
      content
    };
    messages.push(next);
    currentMessageId = id;
    state.currentMessageId = id;
    events.push({ type: "message.append", payload: next });
    return id;
  }

  const tavo: TavoApi = {
    get<T = unknown>(name: string, scope: TavoScope = "chat"): T | undefined {
      return clone(readPath(bucket(scope), name) as T | undefined);
    },
    set<T = unknown>(name: string, value: T, scope: TavoScope = "chat"): void {
      writePath(bucket(scope), name, value);
      events.push({ type: "var.set", payload: { name, scope, value } });
    },
    unset(name: string, scope: TavoScope = "chat"): void {
      deletePath(bucket(scope), name);
      events.push({ type: "var.unset", payload: { name, scope } });
    },
    message: {
      async find(indexRange, filter) {
        return rangeMessages(messages, indexRange).filter((message) => messageMatches(message, filter)).map(clone);
      },
      async get(messageId) {
        return clone(messages.find((message) => message.id === messageId) ?? null);
      },
      async current() {
        return currentMessageId == null ? null : tavo.message.get(currentMessageId);
      },
      async count() {
        return messages.length;
      },
      append: appendMessage,
      async update(message) {
        const index = messages.findIndex((item) => item.id === message.id);
        if (index < 0) return null;
        messages[index] = { ...messages[index]!, ...clone(message) };
        currentMessageId = message.id;
        state.currentMessageId = message.id;
        events.push({ type: "message.update", payload: messages[index] });
        return message.id;
      },
      async delete(messageId) {
        const index = messages.findIndex((message) => message.id === messageId);
        if (index < 0) return null;
        messages.splice(index, 1);
        if (currentMessageId === messageId) {
          currentMessageId = messages.at(-1)?.id ?? null;
          state.currentMessageId = currentMessageId;
        }
        events.push({ type: "message.delete", payload: messageId });
        return messageId;
      }
    },
    chat: {
      async current() {
        return clone(chat);
      },
      async update(next) {
        chat = { ...(chat ?? { id: "mock-chat-1", name: "Mock Chat", characters: [] }), ...clone(next) };
        state.chat = chat;
        events.push({ type: "chat.update", payload: next });
        return clone(chat);
      }
    },
    character: {
      ...characterApi,
      import: async (card) => {
        const data = card && typeof card === "object" && "data" in card ? (card as { data: TavoCharacter }).data : card;
        const created = await character.create(data as TavoCharacter);
        return { characterId: created.id ?? null, lorebookId: null, regexId: null };
      }
    },
    persona: personaApi,
    preset: {
      ...presetApi,
      import: async (value) => (await preset.create(value as TavoPreset)).id ?? null
    },
    lorebook: {
      ...lorebookApi,
      import: async (value) => (await lorebook.create(value as TavoLorebook)).id ?? null
    },
    regex: {
      ...regexApi,
      import: async (value) => (await regex.create(value as TavoRegex)).id ?? null
    },
    memory: {
      async current() {
        return clone(memory);
      },
      async update(next) {
        memory = clone(next);
        state.memory = memory;
        events.push({ type: "memory.update", payload: next });
        return clone(memory);
      }
    },
    async generate(prompt, generateOptions) {
      events.push({ type: "generate", payload: { prompt, options: generateOptions } });
      if (options.generate) return options.generate(prompt, generateOptions, runtime);
      return `mock generation: ${prompt}`;
    },
    input: {
      async get() {
        return state.input;
      },
      set(text) {
        state.input = text;
        events.push({ type: "input.set", payload: text });
      },
      append(text) {
        state.input += text;
        events.push({ type: "input.append", payload: text });
      },
      clear() {
        state.input = "";
        events.push({ type: "input.clear", payload: null });
      },
      send() {
        sentInputs.push(state.input);
        events.push({ type: "input.send", payload: state.input });
        if (state.input) void appendMessage({ role: "user", content: state.input });
        state.input = "";
      }
    },
    utils: {
      toast(text) {
        toasts.push(text);
        events.push({ type: "toast", payload: text });
      },
      openUrl(url) {
        openedUrls.push(url);
        events.push({ type: "openUrl", payload: url });
      },
      export(name, data) {
        exports.push({ name, data });
        events.push({ type: "export", payload: { name, bytes: data.length } });
      },
      async select(selectOptions, title, defaultValue) {
        events.push({ type: "select", payload: { options: selectOptions, title, defaultValue } });
        if (typeof options.select === "function") return options.select(selectOptions, title, defaultValue);
        if ("select" in options) return options.select ?? null;
        if (defaultValue !== undefined) return defaultValue;
        const first = selectOptions[0];
        return typeof first === "string" ? first : first?.value ?? null;
      }
    },
    app: {
      async version() {
        return options.appVersion ?? "0.81.3";
      },
      async versionNumber() {
        return options.appVersionNumber ?? 813;
      }
    }
  };

  const runtime: MockTavoRuntime = { tavo, events, exports, sentInputs, toasts, openedUrls, state };
  return runtime;
}
