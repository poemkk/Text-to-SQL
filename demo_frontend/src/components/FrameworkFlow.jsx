import { useEffect, useState } from "react";
import { api } from "../api.js";
import TaskRouter from "./TaskRouter.jsx";

const inputBlocks = [
  {
    title: "Natural-language question q",
    body: "How many singers do we have?",
    tag: "Input",
  },
  {
    title: "Database schema S",
    body: "singer(singer_id, name, country, age) + foreign keys",
    tag: "Schema",
  },
  {
    title: "Schema context",
    body: "Retrieved tables, columns, key relations and value hints",
    tag: "RAG",
  },
];

const candidateSql = [
  { id: "y1", text: "SELECT COUNT(*) FROM singer;", status: "ok" },
  { id: "y2", text: "SELECT COUNT(*) FROM singers;", status: "fail" },
  { id: "y3", text: "SELECT COUNT(DISTINCT singer_id) FROM singer;", status: "ok" },
];

const pipelineStages = [
  {
    key: "generate",
    index: "1",
    title: "Generate",
    subtitle: "Candidate generation",
    tone: "green",
    content: (
      <>
        <div className="method-list">
          <span>Prompt-only</span>
          <span>BM25 / Schema-RAG</span>
          <span>Embedding RAG</span>
          <span>LoRA + RAG</span>
          <span>Multi-LLM generation</span>
        </div>
        <div className="candidate-box">
          {candidateSql.map((item) => (
            <div key={item.id} className="candidate-row">
              <b>{item.id}</b>
              <code>{item.text}</code>
            </div>
          ))}
        </div>
      </>
    ),
  },
  {
    key: "validate",
    index: "2",
    title: "Validate",
    subtitle: "Execution validation",
    tone: "orange",
    content: (
      <div className="validation-stack">
        {candidateSql.map((item) => (
          <div key={item.id} className={`validation-row ${item.status}`}>
            <b>{item.id}</b>
            <span>{item.status === "ok" ? "Executable" : "Execution error"}</span>
            <small>
              {item.status === "ok" ? "result: r" : "no such table: singers"}
            </small>
          </div>
        ))}
      </div>
    ),
  },
  {
    key: "repair",
    index: "3",
    title: "Repair",
    subtitle: "Error-feedback repair",
    tone: "blue",
    content: (
      <div className="repair-flow">
        <div className="llm-box">
          <span>Input</span>
          <strong>q + S + y2 + error</strong>
          <small>no such table: singers</small>
        </div>
        <div className="repair-arrow">→</div>
        <div className="repaired-sql">
          <span>y2'</span>
          <code>SELECT COUNT(*) FROM singer;</code>
          <small>re-tested: executable</small>
        </div>
      </div>
    ),
  },
  {
    key: "select",
    index: "4",
    title: "Select",
    subtitle: "Final SQL selection",
    tone: "purple",
    content: (
      <div className="selector-box">
        <strong>Lightweight selector</strong>
        <ul>
          <li>executability</li>
          <li>result consistency</li>
          <li>repair history</li>
          <li>error type</li>
        </ul>
        <div className="final-sql">
          <span>y_final</span>
          <code>SELECT COUNT(*) FROM singer;</code>
        </div>
      </div>
    ),
  },
];

const modules = [
  ["G", "Generator", "LLM / cached candidates"],
  ["V", "Validator", "SQL execution engine"],
  ["R", "Repairer", "error feedback"],
  ["Sᵢ", "Selector", "rules / scores"],
  ["E", "Evaluator", "metrics analysis"],
];

const backends = ["SQLite", "DuckDB", "PostgreSQL", "MySQL"];

const routes = [
  {
    key: "sql",
    title: "SQL",
    text: "schema + candidates + SQLite / DuckDB / PostgreSQL / MySQL",
  },
  {
    key: "python",
    title: "Python",
    text: "function/task prompt + unit tests",
  },
  {
    key: "java",
    title: "Java",
    text: "method signature + javac + tests",
  },
];

export default function FrameworkFlow() {
  const [framework, setFramework] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.get("/api/framework").then(setFramework).catch((err) => setError(err.message));
  }, []);

  const steps = framework?.steps || [
    "Input Task",
    "Task Routing",
    "Context Building",
    "Candidate Generation",
    "Validation Environment",
    "Error-feedback Repair",
    "Re-validation / Re-testing",
    "Final Selection",
    "Metrics Evaluation",
  ].map((name, index) => ({ id: index + 1, name }));

  return (
    <div className="page-grid framework-page">
      <section className="architecture-board full">
        <div className="architecture-title">
          <div>
            <h2>A²V-SQL Framework Architecture</h2>
            <p>generate - validate - repair - select</p>
          </div>
          <span>Executable-task prototype</span>
        </div>
        {error && <div className="error-box">{error}</div>}

        <div className="architecture-layout">
          <aside className="architecture-side input-side">
            <div className="side-label">Input</div>
            {inputBlocks.map((item) => (
              <div key={item.title} className="input-card">
                <span>{item.tag}</span>
                <strong>{item.title}</strong>
                <p>{item.body}</p>
              </div>
            ))}
          </aside>

          <section className="core-flow">
            <div className="core-label">A²V-SQL core flow</div>
            <div className="pipeline-grid">
              {pipelineStages.map((stage) => (
                <article key={stage.key} className={`pipeline-card ${stage.tone}`}>
                  <div className="pipeline-card-title">
                    <span>{stage.index}</span>
                    <div>
                      <strong>{stage.title}</strong>
                      <small>{stage.subtitle}</small>
                    </div>
                  </div>
                  {stage.content}
                </article>
              ))}
            </div>

            <div className="module-strip">
              {modules.map(([symbol, title, text]) => (
                <div key={title} className="module-tile">
                  <b>{symbol}</b>
                  <strong>{title}</strong>
                  <small>{text}</small>
                </div>
              ))}
            </div>

            <div className="backend-strip">
              <span>Multi-backend execution</span>
              {backends.map((backend) => (
                <b key={backend}>{backend}</b>
              ))}
            </div>
          </section>

          <aside className="architecture-side evaluation-side">
            <div className="side-label">Evaluation</div>
            <div className="eval-card">
              <strong>Execution result</strong>
              <p>r_final from the selected SQL</p>
            </div>
            <div className="eval-card">
              <strong>Gold comparison</strong>
              <p>Exec(y_final, D) = Exec(y_gold, D)?</p>
            </div>
            <div className="eval-card metric-list-card">
              <strong>Metrics</strong>
              <ul>
                <li>Executable Rate</li>
                <li>Execution Accuracy</li>
                <li>Repair Success Rate</li>
                <li>Final Pass Rate</li>
                <li>Cross-DB Portability</li>
                <li>Latency / Cost</li>
              </ul>
            </div>
          </aside>
        </div>
      </section>

      <section className="panel full">
        <div className="section-heading">
          <h2>{framework?.title || "A²V Framework for LLM-generated executable tasks"}</h2>
          <p>Unified nine-step route used by the prototype backend and frontend.</p>
        </div>
        <div className="flow-grid">
          {steps.map((step) => (
            <div key={step.id} className="flow-step">
              <span>{step.id}</span>
              <strong>{step.name}</strong>
            </div>
          ))}
        </div>
      </section>

      <section className="panel full">
        <div className="section-heading">
          <h2>Task Lines</h2>
          <p>SQL is the thesis main line; Python and Java show transferability.</p>
        </div>
        <div className="route-cards">
          {routes.map((route) => (
            <div key={route.key} className={`route-card ${route.key}`}>
              <strong>{route.title}</strong>
              <span>{route.text}</span>
            </div>
          ))}
        </div>
      </section>

      <TaskRouter />
    </div>
  );
}
