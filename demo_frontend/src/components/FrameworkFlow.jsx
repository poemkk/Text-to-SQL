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

const architectureSteps = [
  {
    title: "Generate",
    desc: "build candidate SQL from question plus schema context",
  },
  {
    title: "Validate",
    desc: "execute each candidate and collect database evidence",
  },
  {
    title: "Repair",
    desc: "rewrite failed SQL using error-feedback and re-validate",
  },
  {
    title: "EASE Select",
    desc: "choose the final practical SQL via evidence-aware semantic arbitration",
  },
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
    subtitle: "EASE final selection",
    tone: "purple",
    content: (
      <div className="selector-box">
        <strong>EASE-Selector</strong>
        <ul>
          <li>question + schema alignment</li>
          <li>candidate SQL structure</li>
          <li>execution evidence + repair trace</li>
          <li>pairwise semantic correction</li>
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
  ["Sₑ", "EASE Selector", "evidence-aware semantic selection"],
  ["E", "Evaluator", "metrics analysis"],
];

const backends = ["SQLite", "DuckDB", "PostgreSQL", "MySQL"];

const selectorSignals = [
  "question-schema alignment",
  "candidate SQL structure",
  "execution evidence and row signal",
  "repair trace and error type",
  "pairwise semantic correction",
];

const selectorRows = [
  ["Rule-based baseline", "77.9%", "exec_ok + source priority + repair flag"],
  ["Multi-LLM practical", "81.6%", "larger candidate pool but weaker final semantic decision"],
  ["EASE-Selector", "85.3%", "semantic evidence + execution evidence + repair trace"],
];

export default function FrameworkFlow() {
  return (
    <div className="page-grid framework-page">
      <section className="architecture-board full">
        <div className="architecture-title">
          <div>
            <h2>A²V-SQL Framework Architecture</h2>
            <p>schema-grounded generation, execution validation, repair and EASE final selection</p>
          </div>
          <span>Prototype architecture overview</span>
        </div>

        <div className="architecture-step-strip">
          {architectureSteps.map((node, index) => (
            <div key={node.title} className="architecture-step-node">
              <span>{index + 1}</span>
              <strong>{node.title}</strong>
              <small>{node.desc}</small>
            </div>
          ))}
        </div>

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

      <section className="panel full selector-logic-panel">
        <div className="section-heading">
          <h2>EASE Selector Logic</h2>
          <p>The final practical SQL is chosen by semantic evidence plus execution evidence.</p>
        </div>

        <div className="selector-logic-grid">
          <div className="selector-logic-card">
            <span className="logic-tag">Input pool</span>
            <strong>Candidate SQL after validation and repair</strong>
            <div className="candidate-box compact">
              {candidateSql.map((item) => (
                <div key={item.id} className="candidate-row compact">
                  <b>{item.id}</b>
                  <code>{item.text}</code>
                </div>
              ))}
            </div>
          </div>

          <div className="selector-logic-card">
            <span className="logic-tag">Evidence</span>
            <strong>EASE semantic features</strong>
            <div className="selector-signal-list">
              {selectorSignals.map((item) => (
                <span key={item}>{item}</span>
              ))}
            </div>
          </div>

          <div className="selector-logic-card final">
            <span className="logic-tag">Output</span>
            <strong>Final selected SQL</strong>
            <pre className="code-block small">SELECT COUNT(*) FROM singer;</pre>
            <p>
              EASE prioritizes executable candidates that best preserve the intended
              semantics of the natural-language question.
            </p>
          </div>
        </div>

        <div className="table-wrap selector-logic-table">
          <table>
            <thead>
              <tr>
                <th>Selector</th>
                <th>Execution accuracy</th>
                <th>Main decision signal</th>
              </tr>
            </thead>
            <tbody>
              {selectorRows.map((row) => (
                <tr key={row[0]}>
                  <td>{row[0]}</td>
                  <td>{row[1]}</td>
                  <td>{row[2]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
