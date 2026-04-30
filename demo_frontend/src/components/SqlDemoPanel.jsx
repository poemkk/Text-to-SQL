import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import RepairPanel from "./RepairPanel.jsx";
import ResultPanel from "./ResultPanel.jsx";
import ValidationPanel from "./ValidationPanel.jsx";

const methods = [
  "prompt_only",
  "bm25_rag",
  "embedding_rag",
  "lora_only",
  "lora_rag",
  "rule_selector_priority",
  "a2v_strong_repair",
];

export default function SqlDemoPanel() {
  const [databases, setDatabases] = useState([]);
  const [dbId, setDbId] = useState("");
  const [examples, setExamples] = useState([]);
  const [schema, setSchema] = useState(null);
  const [method, setMethod] = useState("embedding_rag");
  const [question, setQuestion] = useState("");
  const [generated, setGenerated] = useState(null);
  const [sqlText, setSqlText] = useState("");
  const [execution, setExecution] = useState(null);
  const [repair, setRepair] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .get("/api/sql/databases")
      .then((data) => {
        setDatabases(data);
        if (data[0]) setDbId(data[0].db_id);
      })
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    if (!dbId) return;
    setError(null);
    Promise.all([
      api.get(`/api/sql/examples?db_id=${encodeURIComponent(dbId)}`),
      api.get(`/api/sql/schema?db_id=${encodeURIComponent(dbId)}`),
    ])
      .then(([nextExamples, nextSchema]) => {
        setExamples(nextExamples);
        setSchema(nextSchema);
        setQuestion(nextExamples[0] || "");
        setGenerated(null);
        setSqlText("");
        setExecution(null);
        setRepair(null);
      })
      .catch((err) => setError(err.message));
  }, [dbId]);

  const tableCount = useMemo(() => schema?.tables?.length || 0, [schema]);

  async function generateSql() {
    setError(null);
    setRepair(null);
    setExecution(null);
    try {
      const data = await api.post("/api/sql/generate", {
        db_id: dbId,
        question,
        method,
      });
      setGenerated(data);
      setSqlText(data.selected_sql);
    } catch (err) {
      setError(err.message);
    }
  }

  async function executeSql() {
    setError(null);
    setRepair(null);
    try {
      const data = await api.post("/api/sql/execute", {
        db_id: dbId,
        sql: sqlText,
      });
      setExecution(data);
    } catch (err) {
      setError(err.message);
    }
  }

  async function repairSql() {
    setError(null);
    const hasError = execution && !execution.exec_ok;
    const badSql = hasError ? sqlText : "SELECT count(*) FROM singers;";
    const execError = hasError ? execution.error : "no such table: singers";
    try {
      const data = await api.post("/api/sql/repair_demo", {
        db_id: dbId,
        question,
        bad_sql: badSql,
        error: execError,
      });
      setRepair(data);
      setSqlText(data.repaired_sql);
      setExecution({
        exec_ok: data.exec_ok,
        error: data.exec_error,
        columns: data.columns || [],
        rows: data.rows || [],
        row_count: data.row_count || 0,
      });
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="page-grid sql-page">
      <section className="panel controls-panel">
        <div className="section-heading">
          <h2>SQL Text-to-SQL Demo</h2>
          <p>Spider database task with execution validation.</p>
        </div>
        {error && <div className="error-box">{error}</div>}

        <div className="form-grid">
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
          <label>
            Method
            <select value={method} onChange={(event) => setMethod(event.target.value)}>
              {methods.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label className="wide">
            Example question
            <select
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
            >
              {examples.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label className="wide">
            Question
            <textarea
              rows={3}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
            />
          </label>
        </div>

        <div className="button-row">
          <button className="primary-button" onClick={generateSql} disabled={!dbId || !question}>
            Generate SQL
          </button>
          <button onClick={executeSql} disabled={!sqlText}>
            Execute SQL
          </button>
          <button className="repair-button" onClick={repairSql} disabled={!dbId}>
            Demo Repair
          </button>
        </div>
      </section>

      <section className="panel schema-panel">
        <div className="section-heading">
          <h2>Schema</h2>
          <p>{dbId} · {tableCount} table(s)</p>
        </div>
        <div className="schema-list">
          {schema?.tables?.map((table) => (
            <div key={table.name} className="schema-table">
              <strong>{table.name}</strong>
              <span>{table.columns.map((column) => column.name).join(", ")}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="panel generated-panel">
        <div className="section-heading">
          <h2>Generated SQL</h2>
          <p>{generated?.source || "No candidate selected"}</p>
        </div>
        <textarea
          className="sql-editor"
          rows={7}
          value={sqlText}
          onChange={(event) => setSqlText(event.target.value)}
          placeholder="Generate or paste SQL here"
        />
        {generated?.candidates?.length > 0 && (
          <div className="candidate-strip">
            {generated.candidates.slice(0, 5).map((candidate, index) => (
              <span key={`${candidate.source}-${index}`}>{candidate.source}</span>
            ))}
          </div>
        )}
      </section>

      <ValidationPanel
        title="Validation Environment"
        tone="green"
        steps={[
          "Schema context",
          "Candidate execution",
          "SQLite result check",
          "Error-feedback repair",
          "Re-validation",
        ]}
      />

      <ResultPanel result={execution} />
      <RepairPanel repair={repair} />
    </div>
  );
}
