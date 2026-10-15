import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  acceptanceSchema,
  api,
  assessmentSchema,
  checkSchema,
  projectsSchema,
  proposalSchema,
  recallSchema,
  recordSchema,
} from "./api";
import type {
  Assessment,
  Check,
  Decision,
  Project,
  Requirement,
  Source,
} from "./api";

const labels: Record<Decision["status"], string> = {
  supported: "Supported",
  needs_revalidation: "Needs revalidation",
  contradicted: "Contradicted",
  unknown: "Unknown",
  superseded: "Superseded",
};
const short = (value: string) => value.slice(0, 8);
const shortId = (value: string) => short(value.split(":").at(-1) ?? value);
const message = (error: unknown) =>
  error instanceof Error ? error.message : "The request could not complete.";

function Status({ status }: { status: Decision["status"] }) {
  return (
    <span className={`status status-${status}`}>
      <span aria-hidden="true" />
      {labels[status]}
    </span>
  );
}

function SourceLink({ source }: { source: Source }) {
  return (
    <li>
      {/^https?:\/\//i.test(source.uri) ? (
        <a href={source.uri} target="_blank" rel="noreferrer">
          {source.note || source.uri} ↗
        </a>
      ) : (
        <>
          <span>{source.note || "Repository source"}</span>
          <code>{source.uri}</code>
        </>
      )}
    </li>
  );
}

type Draft = {
  statement: string;
  scope: string;
  reason: string;
  sources: Source[];
  supports: Requirement[][];
};

function DecisionForm({
  project,
  original,
  pending,
  onSubmit,
  onCancel,
}: {
  project: Project;
  original: Decision | null;
  pending: boolean;
  onSubmit: (draft: Draft) => Promise<boolean>;
  onCancel: () => void;
}) {
  const [statement, setStatement] = useState("");
  const [scope, setScope] = useState(original?.scope ?? "");
  const [reason, setReason] = useState("");
  const [sourceUri, setSourceUri] = useState("");
  const [sourceNote, setSourceNote] = useState("");
  const [supports, setSupports] = useState<Requirement[][]>(
    original?.supports ?? [[]],
  );
  const [error, setError] = useState("");

  function selectRequirement(group: number, contract: string, value: string) {
    setSupports(
      supports.map((requirements, index) =>
        index === group
          ? [
              ...requirements.filter((item) => item.contract !== contract),
              ...(value === "unused"
                ? []
                : [{ contract, expected: value === "true" }]),
            ]
          : requirements,
      ),
    );
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (supports.some((group) => group.length === 0)) {
      setError("Select at least one assumption in each support set.");
      return;
    }
    setError("");
    const sources = sourceUri.trim()
      ? [{ uri: sourceUri.trim(), note: sourceNote.trim() }]
      : (original?.sources ?? []);
    if (
      await onSubmit({
        statement: statement.trim(),
        scope: scope.trim(),
        reason: reason.trim(),
        sources,
        supports,
      })
    )
      onCancel();
  }

  return (
    <form
      className="decision-form"
      onSubmit={(event) => {
        void submit(event);
      }}
    >
      <div className="section-heading">
        <div>
          <span className="eyebrow">
            {original ? "Propose a change" : "Create memory"}
          </span>
          <h3>
            {original ? "A new rule. The same scope." : "Record a decision"}
          </h3>
        </div>
        <button
          type="button"
          className="text-button"
          onClick={onCancel}
          disabled={pending}
        >
          Cancel
        </button>
      </div>
      {original ? (
        <p className="muted">
          The current decision remains active until you accept a supported
          proposal.
        </p>
      ) : null}
      <label>
        Decision
        <textarea
          required
          value={statement}
          onChange={(event) => setStatement(event.target.value)}
          placeholder="What should the next agent do?"
          rows={3}
        />
      </label>
      <label>
        Scope
        <input
          required
          value={scope}
          readOnly={Boolean(original)}
          onChange={(event) => setScope(event.target.value)}
          placeholder="For example: keyed-job-requests"
        />
      </label>
      {original ? (
        <label>
          Reason for replacement
          <textarea
            required
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            rows={2}
          />
        </label>
      ) : null}
      <div className="form-supports">
        <p className="field-label">Supporting assumptions</p>
        <p className="muted small">
          All assumptions in a set must hold. Any complete set can support the
          decision.
        </p>
        {supports.map((group, groupIndex) => (
          <fieldset key={groupIndex}>
            <legend>
              Support set {groupIndex + 1}
              {groupIndex > 0 ? " · OR" : ""}
            </legend>
            {project.contracts.map((contract) => (
              <label className="requirement-picker" key={contract.id}>
                <span>
                  {contract.predicate}
                  <code>{contract.id}</code>
                </span>
                <select
                  aria-label={`Expected ${contract.id} in support set ${groupIndex + 1}`}
                  value={
                    group
                      .find((item) => item.contract === contract.id)
                      ?.expected.toString() ?? "unused"
                  }
                  onChange={(event) =>
                    selectRequirement(
                      groupIndex,
                      contract.id,
                      event.target.value,
                    )
                  }
                >
                  <option value="unused">Not required</option>
                  <option value="true">Must be true</option>
                  <option value="false">Must be false</option>
                </select>
              </label>
            ))}
            {supports.length > 1 ? (
              <button
                type="button"
                className="text-button"
                onClick={() =>
                  setSupports(
                    supports.filter((_, index) => index !== groupIndex),
                  )
                }
              >
                Remove set {groupIndex + 1}
              </button>
            ) : null}
          </fieldset>
        ))}
        <button
          type="button"
          className="text-button"
          onClick={() => setSupports([...supports, []])}
        >
          + Add alternative support
        </button>
      </div>
      <div className="form-columns">
        <label>
          Source reference <span className="muted">(optional)</span>
          <input
            value={sourceUri}
            onChange={(event) => setSourceUri(event.target.value)}
            placeholder="https://… or git:sha:path"
          />
        </label>
        <label>
          Source note
          <input
            value={sourceNote}
            onChange={(event) => setSourceNote(event.target.value)}
            placeholder="Why this source matters"
          />
        </label>
      </div>
      {original && !sourceUri ? (
        <p className="muted small">
          The proposal keeps the current source references.
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="inline-error">
          {error}
        </p>
      ) : null}
      <button className="primary" disabled={pending}>
        {pending ? "Saving…" : original ? "Save proposal" : "Record decision"}
      </button>
    </form>
  );
}

function DecisionDetail({
  decision,
  project,
  impacts,
  pending,
  onCheck,
  onPropose,
  onAccept,
}: {
  decision: Decision;
  project: Project;
  impacts: Assessment["affected"];
  pending: boolean;
  onCheck: (contract: string) => void;
  onPropose: () => void;
  onAccept: (proposal: string) => void;
}) {
  const contracts = project.contracts.filter((contract) =>
    decision.supports.some((group) =>
      group.some((item) => item.contract === contract.id),
    ),
  );
  return (
    <article className="decision-detail">
      <div className="detail-title">
        <div className="detail-meta">
          <span className="eyebrow">Decision / {shortId(decision.id)}</span>
          <Status status={decision.status} />
        </div>
        <h2>{decision.statement}</h2>
        <div className="scope">
          <span>Scope</span>
          <code>{decision.scope}</code>
        </div>
        <p className="muted small">
          Recorded at{" "}
          <code title={decision.introduced_sha}>
            {short(decision.introduced_sha)}
          </code>{" "}
          · Viewed at{" "}
          <code title={decision.at_sha}>{short(decision.at_sha)}</code>
        </p>
        {decision.resolution_reason ? (
          <p className="resolution-reason">{decision.resolution_reason}</p>
        ) : null}
        {decision.state === "proposed" ? (
          <div className="proposal-notice">
            <strong>Proposal · not active</strong>
            <p>
              Review the assumptions before you replace the current decision.
            </p>
            <button
              className="primary"
              disabled={
                pending ||
                decision.status !== "supported" ||
                !decision.proposal_id
              }
              onClick={() => {
                if (decision.proposal_id) onAccept(decision.proposal_id);
              }}
            >
              Accept proposal
            </button>
            {decision.status !== "supported" ? (
              <small>
                Acceptance requires supported assumptions at this revision.
              </small>
            ) : null}
          </div>
        ) : decision.status !== "superseded" ? (
          <button className="secondary" disabled={pending} onClick={onPropose}>
            Propose replacement <span aria-hidden="true">↗</span>
          </button>
        ) : (
          <p className="superseded-note">
            Replaced by <code>{shortId(decision.superseded_by ?? "")}</code>.
            Earlier evidence is preserved.
          </p>
        )}
      </div>

      {impacts.length > 0 ? (
        <section className="detail-section">
          <div className="section-heading">
            <h3>Why this decision is affected</h3>
            <span className="eyebrow">Graph traversal</span>
          </div>
          <div className="paths">
            {impacts.map((impact, index) => (
              <ol
                className="dependency-path"
                key={`${impact.contract_id}-${index}`}
                aria-label="Dependency path"
              >
                {impact.path.map((node, nodeIndex) => (
                  <li key={`${node}-${nodeIndex}`} title={node}>
                    <span>
                      {["File", "Contract", "Support", "Decision"][nodeIndex] ??
                        "Node"}
                    </span>
                    <code>
                      {nodeIndex === 1
                        ? impact.contract_id
                        : nodeIndex === 0
                          ? node.replace(/^file:/, "")
                          : nodeIndex === 2
                            ? node.split(":").slice(-2).join(":")
                            : shortId(node)}
                    </code>
                  </li>
                ))}
              </ol>
            ))}
          </div>
          <p className="muted small">
            A connected file changed. The check determines whether the
            assumption still holds.
          </p>
        </section>
      ) : null}

      <section className="detail-section">
        <div className="section-heading">
          <h3>Assumptions & evidence</h3>
          <span className="eyebrow">
            {decision.supports.length} support{" "}
            {decision.supports.length === 1 ? "set" : "sets"}
          </span>
        </div>
        <div className="support-summary">
          {decision.supports.map((group, index) => (
            <div key={index}>
              <span className="support-label">
                {index === 0 ? "Requires" : "Or"}
              </span>
              {group.map((requirement, requirementIndex) => (
                <span key={requirement.contract}>
                  {requirementIndex > 0 ? (
                    <span className="logic-word"> and </span>
                  ) : null}
                  <code>{requirement.contract}</code>
                  <span className="expectation">
                    {" "}
                    = {String(requirement.expected)}
                  </span>
                </span>
              ))}
            </div>
          ))}
        </div>
        {contracts.map((contract) => (
          <div className="contract" key={contract.id}>
            <div className="contract-heading">
              <div>
                <h4>{contract.predicate}</h4>
                <code>{contract.id}</code>
              </div>
              <button
                className="secondary small-button"
                disabled={pending}
                aria-label={`Run check ${contract.id}`}
                onClick={() => onCheck(contract.id)}
              >
                Run check
              </button>
            </div>
            <div className="file-list">
              {contract.paths.map((path) => (
                <code key={path}>{path}</code>
              ))}
            </div>
            {decision.evidence.filter(
              (evidence) => evidence.contract === contract.id,
            ).length === 0 ? (
              <p className="empty-evidence">
                No evidence yet. Run the configured check at this revision.
              </p>
            ) : null}
            {decision.evidence
              .filter((evidence) => evidence.contract === contract.id)
              .map((evidence) => (
                <div
                  className={`evidence evidence-${evidence.freshness}`}
                  key={evidence.id}
                >
                  <div className="evidence-meta">
                    <span className={`outcome outcome-${evidence.outcome}`}>
                      {evidence.outcome}
                    </span>
                    <span>{evidence.freshness}</span>
                    <code title={evidence.observed_sha}>
                      {evidence.observed_sha
                        ? short(evidence.observed_sha)
                        : "No revision"}
                    </code>
                  </div>
                  <p>{evidence.reason}</p>
                  {evidence.freshness === "stale" ? (
                    <p className="stale-note">
                      Historical evidence. It does not establish the result at
                      this revision.
                    </p>
                  ) : null}
                  {evidence.stdout || evidence.stderr ? (
                    <details>
                      <summary>
                        Check output
                        {evidence.exit_code !== null
                          ? ` · exit ${evidence.exit_code}`
                          : ""}
                      </summary>
                      <pre>
                        {evidence.stdout}
                        {evidence.stderr ? `\n${evidence.stderr}` : ""}
                      </pre>
                    </details>
                  ) : null}
                </div>
              ))}
          </div>
        ))}
      </section>
      <div className="detail-bottom">
        <section>
          <h3>Sources</h3>
          {decision.sources.length ? (
            <ul className="sources">
              {decision.sources.map((source, index) => (
                <SourceLink source={source} key={`${source.uri}-${index}`} />
              ))}
            </ul>
          ) : (
            <p className="muted small">No source references recorded.</p>
          )}
        </section>
        <section>
          <h3>History</h3>
          <ol className="history">
            {decision.history.map((event, index) => (
              <li key={`${event.id}-${index}`}>
                <span>{event.kind.replaceAll("_", " ")}</span>
                <code title={event.revision}>{short(event.revision)}</code>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </article>
  );
}

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [revision, setRevision] = useState("");
  const [base, setBase] = useState("");
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [selected, setSelected] = useState("");
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [lastCheck, setLastCheck] = useState<Check | null>(null);
  const [form, setForm] = useState<"closed" | "record" | "replace">("closed");
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [connectionAttempt, setConnectionAttempt] = useState(0);
  const project = projects.find((item) => item.id === projectId);
  const decision =
    decisions.find((item) => item.id === selected) ?? decisions[0];

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    setLoading(true);
    void api("projects", projectsSchema, undefined, controller.signal)
      .then((result) => {
        setProjects(result.projects);
        const initial = result.projects[0];
        setProjectId(initial?.id ?? "");
        setRevision(initial?.revisions.at(-1)?.sha ?? "");
        setBase(initial?.revisions[0]?.sha ?? "");
        if (!initial) setLoading(false);
      })
      .catch((cause) => {
        if (!controller.signal.aborted) {
          setError(message(cause));
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [connectionAttempt]);

  useEffect(() => {
    if (!projectId || !revision) return;
    const controller = new AbortController();
    setLoading(true);
    void api(
      "recall",
      recallSchema,
      { project: projectId, revision },
      controller.signal,
    )
      .then((result) => {
        setDecisions(result.decisions);
        setLoading(false);
      })
      .catch((cause) => {
        if (!controller.signal.aborted) {
          setError(message(cause));
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [projectId, revision, refresh]);

  function changeContext(
    nextProject: Project | undefined,
    nextRevision?: string,
  ) {
    setProjectId(nextProject?.id ?? "");
    setRevision(nextRevision ?? nextProject?.revisions.at(-1)?.sha ?? "");
    setBase(nextProject?.revisions[0]?.sha ?? "");
    setDecisions([]);
    setSelected("");
    setAssessment(null);
    setLastCheck(null);
    setForm("closed");
    setError("");
    setNotice("");
  }

  async function mutate(
    label: string,
    operation: () => Promise<string>,
  ): Promise<boolean> {
    setBusy(label);
    setError("");
    setNotice("");
    try {
      setNotice(await operation());
      setRefresh((value) => value + 1);
      return true;
    } catch (cause) {
      setError(message(cause));
      return false;
    } finally {
      setBusy(null);
    }
  }

  function assess() {
    void mutate("Tracing changed files…", async () => {
      const result = await api("assess_changes", assessmentSchema, {
        project: projectId,
        request_id: crypto.randomUUID(),
        base,
        target: revision,
      });
      setAssessment(result);
      return `${result.changed_paths.length} changed ${result.changed_paths.length === 1 ? "file" : "files"} traced through FalkorDB.`;
    });
  }

  function check(contract: string) {
    void mutate("Running configured check…", async () => {
      const result = await api("run_check", checkSchema, {
        project: projectId,
        request_id: crypto.randomUUID(),
        revision,
        contract,
      });
      setLastCheck(result);
      return `${contract}: ${result.outcome}. Evidence saved at ${short(result.revision)}.`;
    });
  }

  async function save(draft: Draft) {
    return mutate(
      form === "replace" ? "Saving proposal…" : "Recording decision…",
      async () => {
        const common = {
          project: projectId,
          request_id: crypto.randomUUID(),
          revision,
          statement: draft.statement,
          scope: draft.scope,
          sources: draft.sources,
          supports: draft.supports,
        };
        if (form === "replace" && decision) {
          const result = await api("propose_replacement", proposalSchema, {
            ...common,
            replaces: decision.id,
            reason: draft.reason,
          });
          setSelected(result.replacement.id);
          return "Proposal saved. Review its evidence before acceptance.";
        }
        const result = await api("record_decision", recordSchema, common);
        setSelected(result.decision.id);
        return "Decision recorded. Run its checks to establish support.";
      },
    );
  }

  function accept(proposal: string) {
    void mutate("Accepting proposal…", async () => {
      await api("accept_proposal", acceptanceSchema, {
        project: projectId,
        request_id: crypto.randomUUID(),
        proposal_id: proposal,
      });
      return "Replacement accepted. The previous decision and its evidence remain in history.";
    });
  }

  const pending = busy !== null;
  const stale = decisions.filter(
    (item) => item.status === "needs_revalidation" && item.state === "active",
  ).length;
  return (
    <div className="app-shell">
      <aside className="rail">
        <a className="wordmark" href="/" aria-label="Premise home">
          <span className="brand-mark" aria-hidden="true">
            p<span>·</span>
          </span>
          premise
        </a>
        <p className="rail-caption">
          Engineering memory
          <br />
          with a reason to change.
        </p>
        <div className="rail-section">
          <span className="eyebrow">Workspace</span>
          <label className="sr-only" htmlFor="project">
            Project
          </label>
          <select
            id="project"
            value={projectId}
            disabled={pending || projects.length === 0}
            onChange={(event) =>
              changeContext(
                projects.find((item) => item.id === event.target.value),
              )
            }
          >
            {projects.length === 0 ? (
              <option value="">No project loaded</option>
            ) : (
              projects.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.id}
                </option>
              ))
            )}
          </select>
          <div className="rail-current">
            <span aria-hidden="true">◈</span> Decision ledger{" "}
            <span>{decisions.length.toString().padStart(2, "0")}</span>
          </div>
        </div>
        <div className="rail-guide">
          <span className="eyebrow">The memory loop</span>
          <ol>
            <li>
              <span>01</span>Trace the change
            </li>
            <li>
              <span>02</span>Check the assumption
            </li>
            <li>
              <span>03</span>Revise the decision
            </li>
          </ol>
          <p>
            Code changes raise questions.
            <br />
            Evidence answers them.
          </p>
        </div>
        <div className="rail-footer">
          <span className="database-dot" />
          FalkorDB context layer
          <small>Local workspace · explicit evidence</small>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <span>/</span> {projectId || "Connect a project"}
          </div>
          <span className="topbar-note">MEMORY / CONTEXT / PROOF</span>
        </header>
        <div className="workspace">
          <div className="page-heading">
            <div>
              <span className="eyebrow">The context behind your code</span>
              <h1>
                Decision ledger<span>.</span>
              </h1>
              <p>Keep the reasoning. Check what still holds.</p>
            </div>
            <button
              className="primary"
              disabled={!project || pending || loading}
              onClick={() => setForm("record")}
            >
              + Record decision
            </button>
          </div>
          <div className="revision-bar">
            <label>
              View revision
              <select
                aria-label="View revision"
                value={revision}
                disabled={pending || !project}
                onChange={(event) => changeContext(project, event.target.value)}
              >
                {project?.revisions.map((item) => (
                  <option key={item.sha} value={item.sha}>
                    {item.name} · {short(item.sha)}
                  </option>
                ))}
              </select>
            </label>
            <span className="revision-divider" aria-hidden="true" />
            <label>
              Compare from
              <select
                aria-label="Compare from"
                value={base}
                disabled={pending || !project}
                onChange={(event) => {
                  setBase(event.target.value);
                  setAssessment(null);
                }}
              >
                {project?.revisions.map((item) => (
                  <option key={item.sha} value={item.sha}>
                    {item.name} · {short(item.sha)}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="secondary"
              onClick={assess}
              disabled={pending || !revision || !base || loading}
            >
              Trace changes <span aria-hidden="true">→</span>
            </button>
          </div>
          <div className="feedback" aria-live="polite">
            {busy ? (
              <p className="notice busy">
                <span className="activity-dot" />
                {busy}
              </p>
            ) : notice ? (
              <p className="notice">✓ {notice}</p>
            ) : null}
            {error ? (
              <div className="error" role="alert">
                <strong>Could not complete the request.</strong>
                <p>{error}</p>
                <button
                  className="text-button"
                  disabled={pending}
                  onClick={() => {
                    setError("");
                    if (project) setRefresh((value) => value + 1);
                    else setConnectionAttempt((value) => value + 1);
                  }}
                >
                  Retry connection
                </button>
              </div>
            ) : null}
          </div>
          {assessment ? (
            <div className="assessment-strip">
              <span className="eyebrow">Change assessment</span>
              <span>
                <strong>{assessment.changed_paths.length}</strong> files ·{" "}
                <strong>
                  {
                    new Set(assessment.affected.map((item) => item.decision_id))
                      .size
                  }
                </strong>{" "}
                connected decisions
              </span>
              <span className="changed-files">
                {assessment.changed_paths.join(" · ") ||
                  "No files changed in this range."}
              </span>
            </div>
          ) : null}
          {lastCheck ? (
            <div className="latest-check">
              <span className={`outcome outcome-${lastCheck.outcome}`}>
                {lastCheck.outcome}
              </span>
              <span>{lastCheck.reason}</span>
              <code title={lastCheck.revision}>
                {short(lastCheck.revision)}
              </code>
            </div>
          ) : null}
          {form === "record" && project ? (
            <DecisionForm
              key={`record-${projectId}-${revision}`}
              project={project}
              original={null}
              pending={pending}
              onSubmit={save}
              onCancel={() => setForm("closed")}
            />
          ) : null}
          {loading ? (
            <div className="empty-state" role="status">
              <span className="eyebrow">Reading graph memory</span>
              <h2>Loading decisions…</h2>
            </div>
          ) : !project ? (
            <div className="empty-state">
              <span className="empty-symbol" aria-hidden="true">
                ◇
              </span>
              <h2>No project available</h2>
              <p>
                Start the Premise server with a configured project, then retry
                the connection.
              </p>
              <button
                className="secondary"
                onClick={() => setConnectionAttempt((value) => value + 1)}
              >
                Retry connection
              </button>
            </div>
          ) : decisions.length === 0 ? (
            <div className="empty-state">
              <span className="empty-symbol" aria-hidden="true">
                ◇
              </span>
              <h2>No decisions at this revision</h2>
              <p>Record a decision with its scope and assumptions to begin.</p>
            </div>
          ) : (
            <div className="ledger">
              <section className="decision-list" aria-label="Decisions">
                <div className="list-heading">
                  <h2>
                    Stored decisions <span>{decisions.length}</span>
                  </h2>
                  {stale > 0 ? (
                    <p>
                      {stale} need{stale === 1 ? "s" : ""} revalidation
                    </p>
                  ) : (
                    <p>Revision-specific context</p>
                  )}
                </div>
                {decisions.map((item) => (
                  <button
                    key={item.id}
                    className={`decision-card ${item.id === decision?.id ? "selected" : ""}`}
                    aria-pressed={item.id === decision?.id}
                    disabled={pending}
                    onClick={() => {
                      setSelected(item.id);
                      setForm("closed");
                    }}
                  >
                    <div className="card-meta">
                      <span>
                        {item.state === "proposed"
                          ? "Proposal · inactive"
                          : item.scope}
                      </span>
                      <span aria-hidden="true">↗</span>
                    </div>
                    <h3>{item.statement}</h3>
                    <Status status={item.status} />
                    <code className="card-sha">
                      {short(item.introduced_sha)}
                    </code>
                  </button>
                ))}
              </section>
              <div className="detail-column">
                {decision ? (
                  <>
                    <DecisionDetail
                      decision={decision}
                      project={project}
                      impacts={
                        assessment?.affected.filter(
                          (item) => item.decision_id === decision.id,
                        ) ?? []
                      }
                      pending={pending}
                      onCheck={check}
                      onPropose={() => setForm("replace")}
                      onAccept={accept}
                    />
                    {form === "replace" ? (
                      <DecisionForm
                        key={decision.id}
                        project={project}
                        original={decision}
                        pending={pending}
                        onSubmit={save}
                        onCancel={() => setForm("closed")}
                      />
                    ) : null}
                  </>
                ) : null}
              </div>
            </div>
          )}
          <footer className="workspace-footer">
            <span>
              Every result has a revision. Every change keeps its history.
            </span>
            <span>PREMISE / 01</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
