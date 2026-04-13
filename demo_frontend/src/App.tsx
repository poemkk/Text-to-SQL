import { useState } from "react";
import "./App.css";

type AskResponse = {
  method: string;
  db_id: string;
  question: string;
  retrieved_schema: string[];
  sql: string;
  rows: any[][];
  columns: string[];
  error: string | null;
  notes: string;
};

const metricMap: Record<
  string,
  { label: string; execRate: string; execAcc: string; note: string }
> = {
  "prompt-only": {
    label: "Prompt-only",
    execRate: "0.144",
    execAcc: "0.114",
    note: "No schema grounding. Useful as a weak baseline.",
  },
  "bm25-rag": {
    label: "BM25 Schema-RAG",
    execRate: "0.942",
    execAcc: "0.642",
    note: "Sparse retrieval over schema text.",
  },
  "embed-rag": {
    label: "Embedding Schema-RAG",
    execRate: "0.997",
    execAcc: "0.734",
    note: "Best current result on Spider dev.",
  },
  "lora-only": {
    label: "LoRA-only",
    execRate: "0.131",
    execAcc: "0.078",
    note: "Fine-tuning without schema grounding.",
  },
  "lora-rag": {
    label: "LoRA + RAG",
    execRate: "0.985",
    execAcc: "0.600",
    note: "Schema-aware LoRA pipeline.",
  },
};

function App() {
  const [db, setDb] = useState("concert_singer");
  const [method, setMethod] = useState("embed-rag");
  const [question, setQuestion] = useState("How many singers do we have?");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AskResponse | null>(null);

  const runDemo = async () => {
    setLoading(true);
    setResult(null);

    try {
      const resp = await fetch("http://127.0.0.1:8000/ask", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          question,
          db_id: db,
          method,
        }),
      });

      const data = (await resp.json()) as AskResponse;
      setResult(data);
    } catch (err) {
      setResult({
        method,
        db_id: db,
        question,
        retrieved_schema: [],
        sql: "",
        rows: [],
        columns: [],
        error: String(err),
        notes: "Frontend request failed.",
      });
    } finally {
      setLoading(false);
    }
  };

  const metrics = metricMap[method];

  return (
    <div className="app">
      <div className="container">
        <h1>Text-to-SQL Demo System</h1>
        <p className="subtitle">
          自然语言问题 → Schema 检索 → SQL 生成 → SQLite 执行结果
          <br/>
          Вопрос на естественном языке → Поиск схемы → Генерация SQL → Выполнение SQLite
        </p>

        <div className="top-grid">
          <div className="card">
            <h2>Input</h2>

            <label>Database</label>
            <select value={db} onChange={(e) => setDb(e.target.value)}>
              <option value="concert_singer">concert_singer</option>
              <option value="pets_1">pets_1</option>
              <option value="department_management">
                department_management
              </option>
            </select>

            <label>Method</label>
            <select value={method} onChange={(e) => setMethod(e.target.value)}>
              <option value="prompt-only">Prompt-only</option>
              <option value="bm25-rag">BM25 RAG</option>
              <option value="embed-rag">Embedding RAG</option>
              <option value="lora-only">LoRA-only</option>
              <option value="lora-rag">LoRA + RAG</option>
            </select>

            <label>Question</label>
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
            />

            <div className="button-row">
              <button onClick={runDemo} disabled={loading}>
                {loading ? "Running..." : "Run Demo"}
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  setDb("concert_singer");
                  setMethod("embed-rag");
                  setQuestion("How many singers do we have?");
                }}
              >
                Example
              </button>
            </div>
          </div>

          <div className="card">
            <h2>Method Summary</h2>
            <div className="metric-box">
              <div className="metric-title">{metrics.label}</div>
              <div className="metric-row">
                <span>Exec Rate</span>
                <strong>{metrics.execRate}</strong>
              </div>
              <div className="metric-row">
                <span>Exec Acc</span>
                <strong>{metrics.execAcc}</strong>
              </div>
              <p className="note">{metrics.note}</p>
            </div>
          </div>
        </div>

        <div className="card">
          <h2>Pipeline</h2>
          <div className="pipeline">
            <div className="pipe-step">Question</div>
            <div className="pipe-arrow">→</div>
            <div className="pipe-step">Schema Retrieval</div>
            <div className="pipe-arrow">→</div>
            <div className="pipe-step">SQL Generation</div>
            <div className="pipe-arrow">→</div>
            <div className="pipe-step">Execution</div>
            <div className="pipe-arrow">→</div>
            <div className="pipe-step">Result</div>
          </div>
        </div>

        <div className="main-grid">
          <div className="card">
            <h2>Generated SQL</h2>
            <pre>{loading ? "Running..." : result?.sql || ""}</pre>

            <h2>Result</h2>
            {result?.error ? (
              <div className="error-box">{result.error}</div>
            ) : result?.columns && result.columns.length > 0 ? (
              <table>
                <thead>
                  <tr>
                    {result.columns.map((col) => (
                      <th key={col}>{col}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((row, i) => (
                    <tr key={i}>
                      {row.map((cell, j) => (
                        <td key={j}>{String(cell)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="empty-box">
                {loading ? "Running..." : "No result yet."}
              </div>
            )}
          </div>

          <div className="card">
            <h2>Retrieved Schema</h2>
            <pre>
              {result?.retrieved_schema?.length
                ? result.retrieved_schema.join("\n")
                : "This method does not provide schema retrieval output yet."}
            </pre>
          </div>
        </div>

        <div className="card">
          <h2>Thesis Experiment Summary (Spider dev=1034)</h2>
          <table>
            <thead>
              <tr>
                <th>Method</th>
                <th>Exec Rate</th>
                <th>Exec Accuracy</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Prompt-only</td>
                <td>0.144</td>
                <td>0.114</td>
              </tr>
              <tr>
                <td>BM25 Schema-RAG</td>
                <td>0.942</td>
                <td>0.642</td>
              </tr>
              <tr>
                <td>Embedding Schema-RAG</td>
                <td>0.997</td>
                <td>0.734</td>
              </tr>
              <tr>
                <td>LoRA-only (ep3)</td>
                <td>0.131</td>
                <td>0.078</td>
              </tr>
              <tr>
                <td>LoRA + RAG + EGS + Repair</td>
                <td>0.985</td>
                <td>0.600</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export default App;