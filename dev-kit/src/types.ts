export type TavoScope = "chat" | "global";
export type TavoId = string | number;
export type TavoIdLike = TavoId | { id: TavoId };
export type TavoMatchMode = "exact" | "prefix" | "suffix" | "contains";
export type TavoMessageRole = "user" | "assistant" | "system" | (string & {});
export type TavoMessageIndexRange = number | [number?, number?] | [] | null | undefined;

export interface TavoSummary {
  id: TavoId;
  name: string;
  avatar?: string;
  [key: string]: unknown;
}

export interface TavoMessage {
  id: TavoId;
  role: TavoMessageRole;
  content: string;
  characterId?: TavoId;
  reasoning?: string;
  hidden?: boolean;
  [key: string]: unknown;
}

export interface TavoMessageFilter {
  role?: TavoMessageRole;
  hidden?: boolean;
  characters?: Array<TavoId | { id: TavoId }>;
}

export interface TavoChat {
  id: TavoId;
  name: string;
  characters: TavoCharacter[];
  persona?: TavoPersona | null;
  preset?: TavoPreset | null;
  lorebooks?: TavoLorebook[];
  regexes?: TavoRegex[];
  [key: string]: unknown;
}

export interface TavoCharacter {
  id?: TavoId;
  avatar?: string;
  name: string;
  description?: string;
  firstMes?: string;
  first_mes?: string;
  personality?: string;
  scenario?: string;
  mesExample?: string;
  mes_example?: string;
  creatorNotes?: string;
  creator_notes?: string;
  systemPrompt?: string;
  system_prompt?: string;
  postHistoryInstructions?: string;
  post_history_instructions?: string;
  alternateGreetings?: string[] | null;
  alternate_greetings?: string[] | null;
  tags?: string[];
  creator?: string;
  characterVersion?: string;
  character_version?: string;
  nickname?: string;
  groupOnlyGreetings?: string[];
  group_only_greetings?: string[];
  [key: string]: unknown;
}

export interface TavoPersona {
  id?: TavoId;
  name: string;
  description: string;
  avatar?: string;
  active?: boolean;
  sortIndex?: number;
  [key: string]: unknown;
}

export interface TavoPresetEntry {
  identifier: string;
  name: string;
  content?: string;
  enabled?: boolean;
  active?: boolean;
  type?: "builtin" | "marker" | "custom" | (string & {});
  role?: "system" | "user" | "assistant" | "SYSTEM" | "USER" | "ASSISTANT" | (string & {});
  injectionPosition?: string | number;
  injection_position?: number;
  injectionDepth?: number;
  injection_depth?: number;
  [key: string]: unknown;
}

export interface TavoPreset {
  id?: TavoId;
  name: string;
  basicPrompts?: Record<string, unknown>;
  entries?: TavoPresetEntry[];
  prompts?: TavoPresetEntry[];
  [key: string]: unknown;
}

export interface TavoLorebookEntry {
  identifier?: string;
  name?: string;
  content: string;
  enabled?: boolean;
  strategy?: string;
  keywords?: string[];
  secondaryKeywords?: string[];
  secondaryKeywordStrategy?: string;
  scanDepth?: number | null;
  caseSensitive?: boolean | null;
  matchWholeWord?: boolean;
  injectionPosition?: string | number;
  injectionDepth?: number;
  injectionRole?: string | null;
  probability?: number;
  sticky?: number;
  cooldown?: number;
  delay?: number;
  [key: string]: unknown;
}

export interface TavoLorebook {
  id?: TavoId;
  name: string;
  entries: TavoLorebookEntry[] | Record<string, TavoLorebookEntry>;
  [key: string]: unknown;
}

export interface TavoRegexEntry {
  id?: string;
  name: string;
  findRegex: string;
  replaceString: string;
  trimStrings?: string[];
  placements?: string[] | number[];
  placement?: number[];
  timing?: "display" | "send" | "sendAndDisplay" | "receive" | "editAndReceive" | (string & {});
  substitution?: "none" | "raw" | "escaped" | (string & {});
  minDepth?: number | null;
  maxDepth?: number | null;
  enabled?: boolean;
  disabled?: boolean;
  [key: string]: unknown;
}

export interface TavoRegex {
  id?: TavoId;
  name: string;
  entries: TavoRegexEntry[];
  [key: string]: unknown;
}

export interface TavoMemory {
  id?: TavoId;
  enabled: boolean;
  memories: string[];
  [key: string]: unknown;
}

export interface TavoGenerateOptions {
  context?: boolean;
  preset?: TavoIdLike;
  settings?: {
    temperature?: number;
    topP?: number;
    maxCompletionTokens?: number;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface TavoSelectOption {
  value: string;
  label: string;
  description?: string;
  subtitle?: string;
}

export interface TavoResourceApi<T extends { id?: TavoId; name: string }> {
  all(): Promise<T[]>;
  get(id: TavoIdLike): Promise<T | null>;
  find(name: string, options?: { match?: TavoMatchMode }): Promise<T | null>;
  create(value: T): Promise<T>;
  update(value: T & { id: TavoId }): Promise<T>;
  delete(value: TavoIdLike): Promise<boolean>;
}

export interface TavoImportApi<Input = unknown, Output = TavoId | null> {
  import(value: Input): Promise<Output>;
}

export interface TavoApi {
  get<T = unknown>(name: string, scope?: TavoScope): T | undefined;
  set<T = unknown>(name: string, value: T, scope?: TavoScope): void;
  unset(name: string, scope?: TavoScope): void;
  message: {
    find(indexRange?: TavoMessageIndexRange, filter?: TavoMessageFilter): Promise<TavoMessage[]>;
    get(messageId: TavoId): Promise<TavoMessage | null>;
    current(): Promise<TavoMessage | null>;
    count(): Promise<number>;
    append(message: Partial<TavoMessage> & { role: "assistant" | "user"; content: string }): Promise<TavoId | null>;
    update(message: Partial<TavoMessage> & { id: TavoId }): Promise<TavoId | null>;
    delete(messageId: TavoId): Promise<TavoId | null>;
  };
  chat: {
    current(): Promise<TavoChat | null>;
    update(chat: Partial<TavoChat> & { id?: TavoId }): Promise<TavoChat | null>;
  };
  character: TavoResourceApi<TavoCharacter> & TavoImportApi<unknown, { characterId: TavoId | null; lorebookId: TavoId | null; regexId: TavoId | null }>;
  persona: TavoResourceApi<TavoPersona>;
  preset: TavoResourceApi<TavoPreset> & TavoImportApi<unknown, TavoId | null>;
  lorebook: TavoResourceApi<TavoLorebook> & TavoImportApi<unknown, TavoId | null>;
  regex: TavoResourceApi<TavoRegex> & TavoImportApi<unknown, TavoId | null>;
  memory: {
    current(): Promise<TavoMemory | null>;
    update(memory: TavoMemory): Promise<TavoMemory>;
  };
  generate(prompt: string, options?: TavoGenerateOptions): Promise<string | null>;
  input: {
    get(): Promise<string>;
    set(text: string): void;
    append(text: string): void;
    clear(): void;
    send(): void;
  };
  utils: {
    toast(text: string): void;
    openUrl(url: string): void;
    export(name: string, data: string): void;
    select(options: string[] | TavoSelectOption[], title?: string, defaultValue?: string): Promise<string | null>;
  };
  app: {
    version(): Promise<string>;
    versionNumber(): Promise<number>;
  };
}

export type TavoScript<T = unknown> = (tavo: TavoApi) => T | Promise<T>;

export function defineTavoScript<T>(script: TavoScript<T>): TavoScript<T> {
  return script;
}
