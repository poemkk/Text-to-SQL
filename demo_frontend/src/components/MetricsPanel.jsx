import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function MetricsPanel() {
  const [metrics, setMetrics] = useState(null);
  const [error, setError] = useState(null);

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
