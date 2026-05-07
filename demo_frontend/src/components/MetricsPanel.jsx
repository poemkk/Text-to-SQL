import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function MetricsPanel() {
  const [metrics, setMetrics] = useState(null);
  const [error, setError] = useState(null);
  const selector = metrics?.selector_analysis || {};

  useEffect(() => {
    api.get("/api/metrics/overview").then(setMetrics).catch((err) => setError(err.message));
  }, []);

  return (
    <div className="page-grid metrics-page">
      <section className="panel full">
        <div className="section-heading">
          <h2>Metrics Overview</h2>
          <p>Core thesis indicators for SQL and transfer tasks.</p>
        </div>
        {error && <div className="error-box">{error}</div>}
        <div className="metric-cards">
          <MetricCard
            tone="green"
            title="SQL best executable accuracy"
            value={formatPct(0.779)}
            caption="A2V strong repair practical v2"
          />
          <MetricCard
            tone="orange"
            title="Python best final pass"
            value={formatPct(metrics?.python?.best_final_pass)}
            caption="APPS-500 Gemini"
          />
          <MetricCard
            tone="purple"
            title="Java best final pass"
            value={formatPct(metrics?.java?.best_final_pass)}
            caption="MBPP-Java-386 Gemini"
          />
          <MetricCard
            tone="blue"
            title="MySQL executable rate"
            value={formatPct(0.998)}
            caption="Multi-backend validation"
          />
        </div>
      </section>

      <section className="panel full">
        <div className="section-heading">
          <h2>SQL Spider-1034</h2>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Method</th>
                <th>Executable Rate</th>
                <th>Execution Accuracy</th>
              </tr>
            </thead>
            <tbody>
              {(metrics?.sql || []).map((row) => (
                <tr key={row.method}>
                  <td>{row.method}</td>
                  <td>{formatPct(row.exec_rate)}</td>
                  <td>{formatPct(row.exec_acc)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel full">
        <div className="section-heading">
          <h2>Selector Analysis</h2>
          <p>EASE replaces the early rule-based selector as the final practical SQL chooser.</p>
        </div>
        <div className="metric-cards selector-metric-cards">
          <MetricCard
            tone="blue"
            title="Rule-based baseline"
            value={formatPct(selector.rule_based_practical)}
            caption="repair-expanded pool + simple final heuristic"
          />
          <MetricCard
            tone="orange"
            title="Multi-LLM practical"
            value={formatPct(selector.multi_llm_practical)}
            caption="larger pool but selector still limited"
          />
          <MetricCard
            tone="green"
            title="EASE practical"
            value={formatPct(selector.ease_practical)}
            caption="evidence-aware semantic execution arbitration"
          />
          <MetricCard
            tone="purple"
            title="Oracle upper bound"
            value={formatPct(selector.oracle_upper_bound)}
            caption="analysis only, not practical selection"
          />
        </div>
        <div className="table-wrap selector-table-wrap">
          <table>
            <thead>
              <tr>
                <th>Selector type</th>
                <th>Execution Acc.</th>
                <th>Gap to Oracle</th>
                <th>Key evidence</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Rule-based selector</td>
                <td>{formatPct(selector.rule_based_practical)}</td>
                <td>{formatPp(selector.gap_rule)}</td>
                <td>exec_ok, result consistency, repair flag, source priority</td>
              </tr>
              <tr>
                <td>Multi-LLM practical</td>
                <td>{formatPct(selector.multi_llm_practical)}</td>
                <td>{formatPp((selector.oracle_upper_bound || 0) - (selector.multi_llm_practical || 0))}</td>
                <td>larger candidate pool, but still bottlenecked by weak final choice</td>
              </tr>
              <tr>
                <td>EASE / LLM pairwise</td>
                <td>{formatPct(selector.ease_practical)}</td>
                <td>{formatPp(selector.gap_ease)}</td>
                <td>question, schema, SQL structure, execution evidence, repair trace</td>
              </tr>
              <tr>
                <td>Oracle + repair</td>
                <td>{formatPct(selector.oracle_upper_bound)}</td>
                <td>0.0 pp</td>
                <td>gold answer for upper-bound analysis only</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div className="selector-analysis-note">
          The key bottleneck is no longer candidate generation alone. Once repair makes more
          candidates executable, the dominant problem becomes choosing the semantically best
          executable SQL. EASE addresses this by combining question-schema alignment, SQL
          structure, execution evidence and repair trace, which is why the practical gap to
          the oracle upper bound shrinks from {formatPp(selector.gap_rule)} to{" "}
          {formatPp(selector.gap_ease)}.
        </div>
        <div className="metric-cards selector-metric-cards">
          <MetricCard
            tone="red"
            title="Gap reduction"
            value={`${formatPp(selector.gap_rule)} → ${formatPp(selector.gap_ease)}`}
            caption="EASE sharply narrows the selector bottleneck"
          />
          <MetricCard
            tone="green"
            title="Why EASE helps"
            value="semantic + evidence"
            caption="reduces executable-but-wrong SQL among already valid candidates"
          />
        </div>
      </section>

      <section className="panel">
        <div className="section-heading">
          <h2>Python</h2>
        </div>
        <KeyValueRows
          rows={[
            ["Dataset", metrics?.python?.dataset],
            ["Best initial", formatPct(metrics?.python?.best_initial_pass)],
            ["Best final", formatPct(metrics?.python?.best_final_pass)],
          ]}
        />
      </section>

      <section className="panel">
        <div className="section-heading">
          <h2>Java</h2>
        </div>
        <KeyValueRows
          rows={[
            ["Dataset", metrics?.java?.dataset],
            ["Best initial", formatPct(metrics?.java?.best_initial_pass)],
            ["Best final", formatPct(metrics?.java?.best_final_pass)],
          ]}
        />
      </section>

      <section className="panel full">
        <div className="section-heading">
          <h2>Multi-backend</h2>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Backend</th>
                <th>After Exec</th>
                <th>Same Result</th>
              </tr>
            </thead>
            <tbody>
              {(metrics?.multi_backend || []).map((row) => (
                <tr key={row.backend}>
                  <td>{row.backend}</td>
                  <td>{formatPct(row.after_exec)}</td>
                  <td>{formatPct(row.same_result)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function MetricCard({ title, value, caption, tone }) {
  return (
    <div className={`metric-card ${tone}`}>
      <span>{title}</span>
      <strong>{value}</strong>
      <small>{caption}</small>
    </div>
  );
}

function KeyValueRows({ rows }) {
  return (
    <div className="kv-list">
      {rows.map(([key, value]) => (
        <div key={key}>
          <span>{key}</span>
          <strong>{value || "-"}</strong>
        </div>
      ))}
    </div>
  );
}

function formatPct(value) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

function formatPp(value) {
  return `${(Number(value || 0) * 100).toFixed(1)} pp`;
}
