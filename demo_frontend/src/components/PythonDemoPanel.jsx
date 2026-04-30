import { useEffect, useState } from "react";
import { api } from "../api.js";
import RepairPanel from "./RepairPanel.jsx";
import ValidationPanel from "./ValidationPanel.jsx";

export default function PythonDemoPanel() {
  const [summary, setSummary] = useState(null);
  const [examples, setExamples] = useState([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [repair, setRepair] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([api.get("/api/python/summary"), api.get("/api/python/examples")])
      .then(([summaryData, exampleData]) => {
        setSummary(summaryData);
        setExamples(exampleData);
      })
      .catch((err) => setError(err.message));
  }, []);

  const example = examples[selectedIndex];

  async function simulateRepair() {
    if (!example) return;
    setError(null);
    try {
      const data = await api.post("/api/python/repair_demo", {
        code: example.initial_code,
        error: example.initial_error || "Wrong answer",
      });
      setRepair(data);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="page-grid">
      <section className="panel full">
        <div className="section-heading">
          <h2>Python APPS-500 Demo</h2>
          <p>Unit-test validation with error-feedback repair.</p>
        </div>
        {error && <div className="error-box">{error}</div>}
        <ModelTable models={summary?.models || []} />
      </section>

      <section className="panel full">
        <div className="section-heading">
          <h2>Example</h2>
          <p>{summary?.dataset || "APPS-500"}</p>
        </div>
        <div className="form-grid">
          <label className="wide">
            Task
            <select
              value={selectedIndex}
              onChange={(event) => {
                setSelectedIndex(Number(event.target.value));
                setRepair(null);
              }}
            >
              {examples.map((item, index) => (
                <option key={`${item.model}-${index}`} value={index}>
                  {item.model || "model"} · {item.initial_pass ? "initial pass" : "initial fail"}
                </option>
              ))}
            </select>
          </label>
        </div>

        {example && (
          <div className="code-comparison">
            <div>
              <div className="code-title">
                <strong>Initial Code</strong>
                <span className={example.initial_pass ? "badge ok" : "badge fail"}>
                  {example.initial_pass ? "pass" : "fail"}
                </span>
              </div>
              <pre className="code-block">{example.initial_code}</pre>
              <div className={example.initial_pass ? "success-box" : "error-box"}>
                {example.initial_error || "Initial validation passed"}
              </div>
            </div>
            <div>
              <div className="code-title">
                <strong>Final Code</strong>
                <span className={example.final_pass ? "badge ok" : "badge fail"}>
                  {example.final_pass ? "pass" : "fail"}
                </span>
              </div>
              <pre className="code-block">{example.final_code}</pre>
              <div className={example.final_pass ? "success-box" : "error-box"}>
                {example.final_error || "Final validation passed"}
              </div>
            </div>
          </div>
        )}

        <div className="button-row">
          <button className="repair-button" onClick={simulateRepair} disabled={!example}>
            Simulate Repair
          </button>
        </div>
      </section>

      <ValidationPanel
        title="Python A²V Flow"
        tone="orange"
        steps={["Task prompt", "Candidate code", "Unit tests", "Repair", "Re-testing"]}
      />
      <RepairPanel repair={repair} />
    </div>
  );
}

function ModelTable({ models }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Model</th>
            <th>Tasks</th>
            <th>Initial Pass</th>
            <th>Repair Attempted</th>
            <th>Repair Success</th>
            <th>Final Pass</th>
            <th>Improvement</th>
          </tr>
        </thead>
        <tbody>
          {models.map((row) => (
            <tr key={row.model}>
              <td>{row.model}</td>
              <td>{row.tasks}</td>
              <td>{formatPct(row.initial_pass)}</td>
              <td>{row.repair_attempted}</td>
              <td>{formatPct(row.repair_success)}</td>
              <td>{formatPct(row.final_pass)}</td>
              <td>{formatPct(row.improvement)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatPct(value) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}
