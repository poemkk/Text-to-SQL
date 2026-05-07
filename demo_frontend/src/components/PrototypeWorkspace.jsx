import { useState } from "react";
import JavaDemoPanel from "./JavaDemoPanel.jsx";
import PythonDemoPanel from "./PythonDemoPanel.jsx";
import SqlPrototypePanel from "./SqlPrototypePanel.jsx";

export default function PrototypeWorkspace() {
  const [taskType, setTaskType] = useState("sql");

  const routeMeta = {
    sql: {
      route: "Text-to-SQL pipeline",
      validator: "SQLite execution",
      context: "Spider schema context",
    },
    python: {
      route: "Python code-generation pipeline",
      validator: "Unit tests / I-O tests",
      context: "Task prompt + test cases",
    },
    java: {
      route: "Java code-generation pipeline",
      validator: "javac + assertions",
      context: "Method signature + test harness",
    },
  };

  return (
    <div className="workspace-stack compact">
      <section className="workspace-hero compact">
        <div className="workspace-hero-copy compact">
          <span className="workspace-kicker">A²V-SQL Prototype</span>
          <h2>Research prototype for schema grounding, validation, repair and EASE selection</h2>
          <p>
            The interface is optimized for thesis demonstration: users can choose the
            task route, enter a natural-language query, inspect schema context,
            observe validate-repair traces and view the final SQL selected by
            EASE-Selector.
          </p>
          <div className="workspace-task-switch">
            <button
              className={taskType === "sql" ? "workspace-task-button active sql" : "workspace-task-button"}
              onClick={() => setTaskType("sql")}
            >
              SQL
            </button>
            <button
              className={
                taskType === "python" ? "workspace-task-button active python" : "workspace-task-button"
              }
              onClick={() => setTaskType("python")}
            >
              Python
            </button>
            <button
              className={taskType === "java" ? "workspace-task-button active java" : "workspace-task-button"}
              onClick={() => setTaskType("java")}
            >
              Java
            </button>
          </div>
          <p className="workspace-compact-note">
            This is a research prototype for thesis demonstration and reproducible screenshots.
            It reuses cached experiment outputs plus deterministic repair rules.
          </p>
        </div>

        <div className="workspace-route-card">
          <span className="workspace-route-label">Task Route</span>
          <div className="workspace-route-grid">
            <div>
              <span>Route</span>
              <strong>{routeMeta[taskType].route}</strong>
            </div>
            <div>
              <span>Validation environment</span>
              <strong>{routeMeta[taskType].validator}</strong>
            </div>
            <div>
              <span>Context type</span>
              <strong>{routeMeta[taskType].context}</strong>
            </div>
          </div>
        </div>
      </section>

      {taskType === "sql" && <SqlPrototypePanel />}
      {taskType === "python" && <PythonDemoPanel />}
      {taskType === "java" && <JavaDemoPanel />}
    </div>
  );
}
