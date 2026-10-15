import { z } from "zod";

const requirement = z.object({ contract: z.string(), expected: z.boolean() });
const source = z.object({ uri: z.string(), note: z.string() });
export const decisionSchema = z.object({
  id: z.string(),
  statement: z.string(),
  scope: z.string(),
  introduced_sha: z.string(),
  at_sha: z.string(),
  status: z.enum([
    "supported",
    "needs_revalidation",
    "contradicted",
    "unknown",
    "superseded",
  ]),
  state: z.enum(["active", "proposed"]),
  proposal_id: z.string().nullish(),
  resolution_reason: z.string().nullish(),
  sources: z.array(source),
  supports: z.array(z.array(requirement)),
  superseded_by: z.string().nullable(),
  evidence: z.array(
    z.object({
      id: z.string(),
      contract: z.string(),
      observed_sha: z.string(),
      outcome: z.enum(["true", "false", "unknown"]),
      freshness: z.enum(["direct", "inherited", "stale", "missing"]),
      reason: z.string(),
      stdout: z.string(),
      stderr: z.string(),
      exit_code: z.number().nullable(),
    }),
  ),
  history: z.array(
    z.object({ kind: z.string(), id: z.string(), revision: z.string() }),
  ),
});
const projectSchema = z.object({
  id: z.string(),
  revisions: z.array(z.object({ name: z.string(), sha: z.string() })),
  contracts: z.array(
    z.object({
      id: z.string(),
      predicate: z.string(),
      paths: z.array(z.string()),
    }),
  ),
});
export const projectsSchema = z.object({ projects: z.array(projectSchema) });
export const recallSchema = z.object({
  revision: z.string(),
  decisions: z.array(decisionSchema),
});
export const assessmentSchema = z.object({
  assessment_id: z.string(),
  base: z.string(),
  target: z.string(),
  changed_paths: z.array(z.string()),
  affected: z.array(
    z.object({
      decision_id: z.string(),
      contract_id: z.string(),
      path: z.array(z.string()),
    }),
  ),
});
export const checkSchema = z.object({
  run_id: z.string(),
  revision: z.string(),
  contract: z.string(),
  outcome: z.enum(["true", "false", "unknown"]),
  reason: z.string(),
  exit_code: z.number().nullable(),
  stdout: z.string(),
  stderr: z.string(),
});
export const proposalSchema = z.object({
  proposal_id: z.string(),
  replaces: z.string(),
  replacement: decisionSchema,
  state: z.literal("proposed"),
});
export const acceptanceSchema = z.object({
  proposal_id: z.string(),
  state: z.literal("accepted"),
  revision: z.string(),
});
export const recordSchema = z.object({ decision: decisionSchema });
const errorSchema = z.object({
  error: z.object({ code: z.string(), message: z.string() }),
});

export type Decision = z.infer<typeof decisionSchema>;
export type Project = z.infer<typeof projectSchema>;
export type Assessment = z.infer<typeof assessmentSchema>;
export type Check = z.infer<typeof checkSchema>;
export type Requirement = z.infer<typeof requirement>;
export type Source = z.infer<typeof source>;

export async function api<T>(
  path: string,
  schema: z.ZodType<T>,
  body?: object,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`/api/${path}`, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    signal,
  });
  const payload: unknown = await response.json();
  if (!response.ok) {
    const error = errorSchema.safeParse(payload);
    throw new Error(
      error.success
        ? error.data.error.message
        : `Request failed (${response.status}).`,
    );
  }
  return schema.parse(payload);
}
