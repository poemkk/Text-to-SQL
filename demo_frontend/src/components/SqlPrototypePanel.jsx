import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";

const generationMethods = [
  { value: "baseline", label: "Baseline" },
  { value: "online_llm", label: "Online LLM" },
];

const BASELINE_BACKEND_METHOD = "a2v_strong_repair";

export default function SqlPrototypePanel() {
  const [databases, setDatabases] = useState([]);
  const [dbId, setDbId] = useState("");
  const [method, setMethod] = useState("baseline");
  const [question, setQuestion] = useState("");
  const [pipeline, setPipeline] = useState(null);
  const [expandedTraces, setExpandedTraces] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .get("/api/sql/databases")
      .then((data) => {
        setDatabases(data);
        if (data[0]) {
          setDbId(data[0].db_id);
        }
      })
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    if (!dbId) return;
    setError(null);
    setPipeline(null);
    setExpandedTraces({});
  }, [dbId]);

  const currentDatabase = useMemo(
    () => databases.find((item) => item.db_id === dbId),
    [databases, dbId],
  );

  const repairTrace = useMemo(
    () => pipeline?.candidate_traces?.find((item) => item.repair) || null,
    [pipeline],
  );
  const allTraces = pipeline?.candidate_traces || [];
  const selectedTrace = useMemo(
    () =>
      allTraces.find(
        (item) =>
          item.source === pipeline?.selection?.selected_source &&
          item.final_sql === pipeline?.selection?.selected_sql,
      ) || null,
    [allTraces, pipeline],
  );
  const traceEntries = useMemo(
    () =>
      allTraces.map((trace, index) => {
        const traceKey = `${trace.source}-${index}`;
        return {
          trace,
          traceKey,
          isSelected:
            trace.source === pipeline?.selection?.selected_source &&
            trace.final_sql === pipeline?.selection?.selected_sql,
        };
      }),
    [allTraces, pipeline],
  );
  const primaryTraceEntries = useMemo(() => {
    if (method !== "baseline") return traceEntries;
    const selectedEntries = traceEntries.filter((entry) => entry.isSelected);
    return selectedEntries.length ? selectedEntries : traceEntries.slice(0, 1);
  }, [method, traceEntries]);
  const hiddenTraceEntries = useMemo(() => {
    if (method !== "baseline") return [];
    const primaryKeys = new Set(primaryTraceEntries.map((entry) => entry.traceKey));
    return traceEntries.filter((entry) => !primaryKeys.has(entry.traceKey));
  }, [method, primaryTraceEntries, traceEntries]);
  const backendMethod = method === "baseline" ? BASELINE_BACKEND_METHOD : method;

  async function runPipeline() {
    setLoading(true);
    setError(null);
    try {
      const data = await api.post("/api/sql/run_pipeline", {
        db_id: dbId,
        question: question.trim(),
        method: backendMethod,
        selector: "ease_selector",
      });
      setPipeline(data);
      setExpandedTraces({});
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function toggleTraceDetails(traceKey) {
    setExpandedTraces((current) => ({
      ...current,
      [traceKey]: !current[traceKey],
    }));
  }

  return (
    <div className="page-grid prototype-sql-page">
      <section className="panel full prototype-control-panel compact">
        <div className="section-heading">
          <h2>A²V-SQL Interactive Prototype</h2>
          <p>
            Natural-language input, task type selection, schema grounding, validation,
            repair and final EASE selection in one workflow.
          </p>
        </div>
        {error && <div className="error-box">{error}</div>}

        <div className="prototype-task-row">
          <div className="prototype-task-pill active">SQL</div>
          <div className="prototype-task-pill">Python</div>
          <div className="prototype-task-pill">Java</div>
        </div>

        <div className="prototype-stat-row compact">
          <div className="prototype-stat">
            <span>Database</span>
            <strong>{dbId || "-"}</strong>
          </div>
          <div className="prototype-stat">
            <span>Tables</span>
            <strong>{currentDatabase?.tables?.length || 0}</strong>
          </div>
          <div className="prototype-stat">
            <span>Generation method</span>
            <strong>{method === "baseline" ? "Baseline" : "Online LLM"}</strong>
          </div>
        </div>
        {pipeline && method === "online_llm" && pipeline.generation_runtime !== "online_llm" && (
          <div className="error-box">
            Online LLM candidate generation is unavailable in this run (missing API key or API
            call failed), so the pipeline fell back to dynamic SQL generation.
          </div>
        )}

        <div className="form-grid prototype-form-grid compact">
          <label>
            Database
            <select value={dbId} onChange={(event) => setDbId(event.target.value)}>
              {databases.map((db) => (
                <option key={db.db_id} value={db.db_id}>
                  {db.db_id}
                </option>
              ))}
            </select>
          </label>

          <fieldset className="generation-choice-group">
            <legend>Generation method</legend>
            <div className="generation-choice-row">
              {generationMethods.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  className={method === item.value ? "generation-choice active" : "generation-choice"}
                  onClick={() => {
                    setMethod(item.value);
                    setPipeline(null);
                    setExpandedTraces({});
                  }}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </fieldset>

          <label className="wide compact-input">
            Natural-language question
            <textarea
              rows={2}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask the database in natural language"
            />
          </label>
        </div>

        <div className="button-row">
          <button
            className="primary-button"
            onClick={runPipeline}
            disabled={!dbId || !question.trim() || loading}
          >
            {loading ? "Running pipeline..." : "Run A²V-SQL"}
          </button>
        </div>
      </section>

      <section className="panel schema-context-panel">
        <div className="section-heading stacked">
          <h2>Schema Context</h2>
          <p>{pipeline?.schema_context?.retrieval_strategy || "Run the pipeline to build context."}</p>
        </div>
        {pipeline ? (
          <>
            <div className="token-row">
              {(pipeline.schema_context.question_tokens || []).map((token) => (
                <span key={token}>{token}</span>
              ))}
            </div>
            <div className="schema-context-grid">
              {pipeline.schema_context.tables.map((table) => (
                <article key={table.name} className="schema-context-card">
                  <div className="schema-context-card-header">
                    <strong>{table.name}</strong>
                    <span>{table.match_reason}</span>
                  </div>
                  <div className="column-chip-grid">
                    {table.columns.map((column) => (
                      <span
                        key={`${table.name}-${column.name}`}
                        className={column.highlighted ? "column-chip highlighted" : "column-chip"}
                      >
                        {column.name}
                      </span>
                    ))}
                  </div>
                </article>
              ))}
            </div>
            <div className="relationship-list">
              {(pipeline.schema_context.foreign_keys || []).map((fk) => (
                <div key={`${fk.from}-${fk.to}`} className="relationship-row">
                  <span>{fk.from}</span>
                  <b>→</b>
                  <span>{fk.to}</span>
                </div>
              ))}
            </div>
            <pre className="code-block small">{pipeline.schema_context.context_text}</pre>
          </>
        ) : (
          <p className="muted">
            The prototype highlights only the schema elements most relevant to the current
            question instead of showing the entire database definition.
          </p>
        )}
      </section>

      <section className="panel candidate-trace-panel">
        <div className="section-heading">
          <h2>Candidate SQL and Validation Trace</h2>
          <p>Executable evidence is recorded for each candidate before final selection.</p>
        </div>
        {pipeline ? (
          <div className="candidate-trace-wrap">
            <div className="candidate-trace-list">
              {primaryTraceEntries.map((entry) => (
                <CandidateTraceCard
                  key={entry.traceKey}
                  trace={entry.trace}
                  traceKey={entry.traceKey}
                  isSelected={entry.isSelected}
                  isExpanded={Boolean(expandedTraces[entry.traceKey])}
                  onToggle={toggleTraceDetails}
                />
              ))}
            </div>
            {method === "baseline" && hiddenTraceEntries.length > 0 && (
              <details className="candidate-extra-details">
                <summary>Other baseline candidates ({hiddenTraceEntries.length})</summary>
                <div className="candidate-trace-list compact">
                  {hiddenTraceEntries.map((entry) => (
                    <CandidateTraceCard
                      key={entry.traceKey}
                      trace={entry.trace}
                      traceKey={entry.traceKey}
                      isSelected={entry.isSelected}
                      isExpanded={Boolean(expandedTraces[entry.traceKey])}
                      onToggle={toggleTraceDetails}
                    />
                  ))}
                </div>
              </details>
            )}
            <section className="inline-repair-panel">
              <div className="section-heading compact">
                <h3>Validate → Repair → Re-validate</h3>
                <p>The failed SQL, database error and repaired result are kept together.</p>
              </div>
              {repairTrace ? (
                <div className="repair-focus-grid">
                  <div>
                    <span className="label">Failed SQL</span>
                    <pre className="code-block small">{repairTrace.sql}</pre>
                  </div>
                  <div>
                    <span className="label">SQLite error</span>
                    <div className="error-box">{repairTrace.initial_execution.error}</div>
                  </div>
                  <div>
                    <span className="label">Repair SQL</span>
                    <pre className="code-block small">{repairTrace.repair.repaired_sql}</pre>
                  </div>
                  <div>
                    <span className="label">Re-validation result</span>
                    <div className={repairTrace.repair.exec_ok ? "success-box" : "error-box"}>
                      {repairTrace.repair.exec_ok
                        ? `Executable after repair (${repairTrace.repair.row_count} row(s))`
                        : repairTrace.repair.exec_error}
                    </div>
                  </div>
                </div>
              ) : (
                <p className="muted">
                  When a candidate fails, this area shows the database error and repaired SQL.
                </p>
              )}
            </section>
          </div>
        ) : (
          <p className="muted">No candidate trace yet.</p>
        )}
      </section>

      <section className="panel selector-decision-panel">
        <div className="section-heading">
          <h2>Final Selector Decision</h2>
          <p>Evidence cards used by the final practical selector.</p>
        </div>
        {pipeline ? (
          <>
            <div className="selector-summary-grid">
              <div className="selector-summary-item">
                <span>Selector</span>
                <strong>{pipeline.selection.selector_type}</strong>
              </div>
              <div className="selector-summary-item">
                <span>Selector family</span>
                <strong>{pipeline.selection.selector_family}</strong>
              </div>
              <div className="selector-summary-item">
                <span>Selected source</span>
                <strong>{pipeline.selection.selected_source}</strong>
              </div>
            </div>
            <pre className="code-block">{pipeline.selection.selected_sql}</pre>
            <div className="selector-decision-grid">
              <article className="selector-decision-card">
                <MathSymbol base="q" />
                <strong>User Question</strong>
                <p>{pipeline.question}</p>
              </article>
              <article className="selector-decision-card">
                <MathSymbol base="S" />
                <strong>Schema Context</strong>
                <p>{(pipeline.schema_context?.tables || []).map((item) => item.name).join(", ")}</p>
              </article>
              <article className="selector-decision-card">
                <MathSymbol base="s" sub="j" />
                <strong>Candidate Structure</strong>
                <p>selected SQL candidate structure</p>
              </article>
              <article className="selector-decision-card">
                <MathSymbol base="v" sub="j" />
                <strong>Execution Evidence</strong>
                <p>
                  {pipeline.final_result.exec_ok
                    ? `execution ok, ${pipeline.final_result.row_count} row(s)`
                    : `execution error: ${pipeline.final_result.error || "unknown"}`}
                </p>
              </article>
              <article className="selector-decision-card">
                <MathSymbol base="τ" sub="j" />
                <strong>Repair Trace</strong>
                <p>
                  {selectedTrace?.repair?.repair_success
                    ? "repaired then re-validated"
                    : "selected without repair"}
                </p>
              </article>
              <article className="selector-decision-card">
                <MathSymbol base="C" />
                <strong>Candidate Consistency</strong>
                <p>
                  {pipeline.final_result.exec_ok
                    ? "execution-supported candidate"
                    : "weak evidence"}
                </p>
              </article>
              <article className="selector-decision-card">
                <MathSymbol base="src" />
                <strong>Final Source</strong>
                <p>
                  {pipeline.selection.selected_source}
                  {pipeline.selection.selected_variant ? ` (${pipeline.selection.selected_variant})` : ""}
                </p>
              </article>
            </div>
          </>
        ) : (
          <p className="muted">No selector result yet.</p>
        )}
      </section>

      <section className="panel result-panel">
        <div className="section-heading">
          <h2>Final Execution Result</h2>
          <p>
            {pipeline?.final_result?.exec_ok
              ? `${pipeline.final_result.row_count} row(s)`
              : "Run the pipeline to view the final answer table."}
          </p>
        </div>
        {pipeline?.final_result?.exec_ok ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {pipeline.final_result.columns.map((column) => (
                    <th key={column}>{column}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pipeline.final_result.rows.map((row, rowIndex) => (
                  <tr key={rowIndex}>
                    {row.map((cell, cellIndex) => (
                      <td key={cellIndex}>{String(cell)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : pipeline?.final_result ? (
          <div className="error-box">{pipeline.final_result.error}</div>
        ) : (
          <p className="muted">No execution result yet.</p>
        )}
      </section>
    </div>
  );
}

function CandidateTraceCard({ trace, traceKey, isSelected, isExpanded, onToggle }) {
  return (
    <article className={isSelected ? "candidate-trace-card selected" : "candidate-trace-card"}>
      <div className="candidate-card-header">
        <div>
          <strong>{trace.source}</strong>
          <span>ease score {trace.score}</span>
        </div>
        <div className="candidate-status-group">
          <StatusBadge ok={trace.initial_execution.exec_ok}>
            {trace.initial_execution.exec_ok ? "initial exec ok" : "initial exec failed"}
          </StatusBadge>
          <StatusBadge ok={trace.final_execution.exec_ok}>
            {trace.final_execution.exec_ok ? "final exec ok" : "final exec failed"}
          </StatusBadge>
          {isSelected && <span className="selected-pill">selected</span>}
          <button
            type="button"
            className="trace-details-btn"
            onClick={() => onToggle(traceKey)}
          >
            {isExpanded ? "hide details" : "details"}
          </button>
        </div>
      </div>

      <div className="trace-summary-line">
        <span className="trace-summary-label">SQL</span>
        <code>{(trace.final_sql || trace.sql || "").split("\n").join(" ").trim()}</code>
      </div>

      <div className="candidate-footer-line">
        <span>Rows</span>
        <strong>{trace.final_execution.row_count}</strong>
      </div>

      {isExpanded && (
        <>
          <div className="candidate-sql-block">
            <span>Original SQL</span>
            <pre className="code-block small">{trace.sql}</pre>
          </div>

          {!trace.initial_execution.exec_ok && (
            <div className="candidate-error-box">
              <span>Execution error</span>
              <strong>{trace.initial_execution.error}</strong>
            </div>
          )}

          {trace.repair && (
            <div className="candidate-sql-block repair">
              <span>Repair SQL</span>
              <pre className="code-block small">{trace.repair.repaired_sql}</pre>
              <p>{trace.repair.repair_reason}</p>
            </div>
          )}
        </>
      )}
    </article>
  );
}

function StatusBadge({ ok, children }) {
  return <span className={ok ? "status-chip ok" : "status-chip fail"}>{children}</span>;
}

function MathSymbol({ base, sub = "" }) {
  return (
    <span className="selector-symbol">
      <span className="math-symbol-base">{base}</span>
      {sub ? <sub>{sub}</sub> : null}
    </span>
  );
}
