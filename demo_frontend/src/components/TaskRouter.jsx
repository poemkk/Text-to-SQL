import { useState } from "react";
import { api } from "../api.js";

const sampleQuestions = {
  sql: "How many singers do we have?",
  python: "Given a list of numbers, return the sum.",
  java: "Write a function to identify non-prime numbers.",
};

export default function TaskRouter() {
  const [taskType, setTaskType] = useState("sql");
  const [route, setRoute] = useState(null);
  const [error, setError] = useState(null);

  async function routeTask(nextType = taskType) {
    setError(null);
    try {
      const data = await api.post("/api/route_task", {
        task_type: nextType,
        question: sampleQuestions[nextType],
      });
      setRoute(data);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <section className="panel">
      <div className="section-heading">
        <h2>Task Routing</h2>
        <p>Route the input task to a validation environment.</p>
      </div>

      <div className="segmented">
        {["sql", "python", "java"].map((type) => (
          <button
            key={type}
            className={taskType === type ? `segment active ${type}` : "segment"}
            onClick={() => {
              setTaskType(type);
              routeTask(type);
            }}
          >
            {type.toUpperCase()}
          </button>
        ))}
      </div>

      <div className="route-result">
        {route ? (
          <>
            <strong>{route.route}</strong>
            <span>{route.context_type}</span>
            <span>{route.validation_environment}</span>
          </>
        ) : (
          <button className="primary-button" onClick={() => routeTask()}>
            Route task
          </button>
        )}
      </div>
      {error && <div className="error-box">{error}</div>}
    </section>
  );
}
