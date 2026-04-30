import { useState } from "react";
import FrameworkFlow from "./components/FrameworkFlow.jsx";
import SqlDemoPanel from "./components/SqlDemoPanel.jsx";
import PythonDemoPanel from "./components/PythonDemoPanel.jsx";
import JavaDemoPanel from "./components/JavaDemoPanel.jsx";
import MetricsPanel from "./components/MetricsPanel.jsx";

const tabs = [
  { id: "framework", label: "Framework Overview" },
  { id: "sql", label: "SQL Text-to-SQL Demo" },
  { id: "python", label: "Python APPS-500 Demo" },
  { id: "java", label: "Java MBPP-Java-386 Demo" },
  { id: "metrics", label: "Metrics Overview" },
];

export default function App() {
  const [activeTab, setActiveTab] = useState("framework");

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <h1>A²V Prototype</h1>
          <p>Validation and evaluation framework for LLM-generated SQL / Python / Java</p>
        </div>
        <div className="status-pill">Demo mode</div>
      </header>

      <nav className="tabs" aria-label="A2V prototype tabs">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={activeTab === tab.id ? "tab active" : "tab"}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <main>
        {activeTab === "framework" && <FrameworkFlow />}
        {activeTab === "sql" && <SqlDemoPanel />}
        {activeTab === "python" && <PythonDemoPanel />}
        {activeTab === "java" && <JavaDemoPanel />}
        {activeTab === "metrics" && <MetricsPanel />}
      </main>
    </div>
  );
}
