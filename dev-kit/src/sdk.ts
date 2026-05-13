import type {
  TavoApi,
  TavoChat,
  TavoGenerateOptions,
  TavoId,
  TavoIdLike,
  TavoMemory,
  TavoMessage,
  TavoMessageFilter,
  TavoMessageIndexRange,
  TavoScope,
  TavoSelectOption
} from "./types.js";

export interface TavoSDK {
  readonly raw: TavoApi;
  vars: {
    get<T = unknown>(name: string, scope?: TavoScope): T | undefined;
    set<T = unknown>(name: string, value: T, scope?: TavoScope): T;
    unset(name: string, scope?: TavoScope): void;
    chat: {
      get<T = unknown>(name: string): T | undefined;
      set<T = unknown>(name: string, value: T): T;
      unset(name: string): void;
    };
    global: {
      get<T = unknown>(name: string): T | undefined;
      set<T = unknown>(name: string, value: T): T;
      unset(name: string): void;
    };
  };
  messages: {
    find(indexRange?: TavoMessageIndexRange, filter?: TavoMessageFilter): Promise<TavoMessage[]>;
    get(id: TavoId): Promise<TavoMessage | null>;
    current(): Promise<TavoMessage | null>;
    count(): Promise<number>;
    append(role: "assistant" | "user", content: string, extra?: Partial<TavoMessage>): Promise<TavoId | null>;
    update(id: TavoId, patch: Partial<TavoMessage>): Promise<TavoId | null>;
    delete(id: TavoId): Promise<TavoId | null>;
  };
  chat: {
    current(): Promise<TavoChat | null>;
    rename(name: string): Promise<TavoChat | null>;
    patch(update: Partial<TavoChat> & { id?: TavoId }): Promise<TavoChat | null>;
  };
  memory: {
    current(): Promise<TavoMemory | null>;
    add(text: string): Promise<TavoMemory | null>;
    remove(predicate: string | RegExp | ((item: string) => boolean)): Promise<TavoMemory | null>;
    replace(items: string[], enabled?: boolean): Promise<TavoMemory | null>;
  };
  input: {
    get(): Promise<string>;
    set(text: string): void;
    append(text: string): void;
    replace(search: string | RegExp, replacement: string): Promise<string>;
    clear(): void;
    send(): void;
  };
  generate(prompt: string, options?: TavoGenerateOptions): Promise<string | null>;
  select(options: string[] | TavoSelectOption[], title?: string, defaultValue?: string): Promise<string | null>;
  toast(text: string): void;
}

function scopeVars(tavo: TavoApi, scope: TavoScope) {
  return {
    get<T = unknown>(name: string): T | undefined {
      return tavo.get<T>(name, scope);
    },
    set<T = unknown>(name: string, value: T): T {
      tavo.set(name, value, scope);
      return value;
    },
    unset(name: string): void {
      tavo.unset(name, scope);
    }
  };
}

function memoryPredicate(predicate: string | RegExp | ((item: string) => boolean)): (item: string) => boolean {
  if (typeof predicate === "function") return predicate;
  if (predicate instanceof RegExp) return (item) => predicate.test(item);
  return (item) => item === predicate;
}

async function requireMemory(tavo: TavoApi): Promise<TavoMemory | null> {
  const memory = await tavo.memory.current();
  if (!memory) return null;
  return { ...memory, memories: Array.isArray(memory.memories) ? [...memory.memories] : [] };
}

export function createTavoSDK(tavo: TavoApi): TavoSDK {
  const chatVars = scopeVars(tavo, "chat");
  const globalVars = scopeVars(tavo, "global");

  return {
    raw: tavo,
    vars: {
      get: (name, scope = "chat") => tavo.get(name, scope),
      set<T = unknown>(name: string, value: T, scope: TavoScope = "chat"): T {
        tavo.set(name, value, scope);
        return value;
      },
      unset: (name, scope = "chat") => tavo.unset(name, scope),
      chat: chatVars,
      global: globalVars
    },
    messages: {
      find: (indexRange, filter) => tavo.message.find(indexRange, filter),
      get: (id) => tavo.message.get(id),
      current: () => tavo.message.current(),
      count: () => tavo.message.count(),
      append: (role, content, extra = {}) => tavo.message.append({ ...extra, role, content }),
      update: (id, patch) => tavo.message.update({ ...patch, id }),
      delete: (id) => tavo.message.delete(id)
    },
    chat: {
      current: () => tavo.chat.current(),
      async rename(name) {
        const current = await tavo.chat.current();
        return tavo.chat.update({ id: current?.id, name });
      },
      patch: (update) => tavo.chat.update(update)
    },
    memory: {
      current: () => tavo.memory.current(),
      async add(text) {
        const memory = await requireMemory(tavo);
        if (!memory) return null;
        memory.memories.push(text);
        memory.enabled = true;
        return tavo.memory.update(memory);
      },
      async remove(predicate) {
        const memory = await requireMemory(tavo);
        if (!memory) return null;
        const shouldRemove = memoryPredicate(predicate);
        memory.memories = memory.memories.filter((item) => !shouldRemove(item));
        return tavo.memory.update(memory);
      },
      async replace(items, enabled = true) {
        const memory = await requireMemory(tavo);
        if (!memory) return null;
        memory.memories = [...items];
        memory.enabled = enabled;
        return tavo.memory.update(memory);
      }
    },
    input: {
      get: () => tavo.input.get(),
      set: (text) => tavo.input.set(text),
      append: (text) => tavo.input.append(text),
      async replace(search, replacement) {
        const next = (await tavo.input.get()).replace(search, replacement);
        tavo.input.set(next);
        return next;
      },
      clear: () => tavo.input.clear(),
      send: () => tavo.input.send()
    },
    generate: (prompt, options) => tavo.generate(prompt, options),
    select: (options, title, defaultValue) => tavo.utils.select(options, title, defaultValue),
    toast: (text) => tavo.utils.toast(text)
  };
}

export const tavoSDK = {
  create: createTavoSDK
};

export function normalizeResourceId(value: TavoIdLike): TavoId {
  return typeof value === "object" ? value.id : value;
}
