import { z } from "zod";

export const CharaCardV3Schema = z.object({
  spec: z.literal("chara_card_v3"),
  spec_version: z.string(),
  data: z.object({
    name: z.string().min(1),
    description: z.string(),
    first_mes: z.string().min(1),
    personality: z.string().optional(),
    scenario: z.string().optional(),
    mes_example: z.string().optional(),
    creator_notes: z.string().optional(),
    system_prompt: z.string().optional(),
    post_history_instructions: z.string().optional(),
    alternate_greetings: z.array(z.string()).nullable().optional(),
    character_book: z.unknown().nullable().optional(),
    tags: z.array(z.string()).optional(),
    creator: z.string().optional(),
    character_version: z.string().optional(),
    extensions: z.record(z.string(), z.unknown()).optional()
  }).passthrough()
});

export const WorldbookEntrySchema = z.object({
  uid: z.number(),
  key: z.array(z.string()),
  keysecondary: z.array(z.string()),
  comment: z.string(),
  content: z.string(),
  constant: z.boolean(),
  vectorized: z.boolean(),
  selective: z.boolean(),
  selectiveLogic: z.number(),
  addMemo: z.boolean(),
  order: z.number(),
  position: z.number(),
  disable: z.boolean(),
  probability: z.number(),
  depth: z.number().nullable(),
  displayIndex: z.number()
}).passthrough();

export const WorldbookImportSchema = z.object({
  name: z.string().min(1),
  entries: z.record(z.string(), WorldbookEntrySchema)
});

export const RegexImportSchema = z.array(z.object({
  id: z.string().min(1),
  scriptName: z.string().min(1),
  findRegex: z.string().min(1),
  replaceString: z.string(),
  trimStrings: z.array(z.string()).default([]),
  placement: z.array(z.number()).optional(),
  placements: z.array(z.union([z.string(), z.number()])).optional(),
  disabled: z.boolean().optional(),
  markdownOnly: z.boolean().optional(),
  promptOnly: z.boolean().optional(),
  runOnEdit: z.boolean().optional(),
  substituteRegex: z.number().optional(),
  minDepth: z.number().nullable().optional(),
  maxDepth: z.number().nullable().optional()
}).passthrough());

export const PresetImportSchema = z.object({
  prompts: z.array(z.object({
    identifier: z.string(),
    name: z.string(),
    content: z.string().optional(),
    role: z.string().optional(),
    injection_position: z.number().optional(),
    injection_depth: z.number().optional(),
    enabled: z.boolean().optional()
  }).passthrough()),
  prompt_order: z.array(z.object({
    character_id: z.number(),
    order: z.array(z.object({
      identifier: z.string(),
      enabled: z.boolean()
    }).passthrough())
  }).passthrough()).optional()
}).passthrough();

export const ManifestSchema = z.object({
  suiteId: z.string(),
  generatedAt: z.string(),
  files: z.array(z.object({
    kind: z.string(),
    path: z.string(),
    sha256: z.string()
  })),
  validation: z.array(z.object({
    kind: z.string(),
    ok: z.boolean(),
    message: z.string()
  }))
});

export type TavoManifest = z.infer<typeof ManifestSchema>;

