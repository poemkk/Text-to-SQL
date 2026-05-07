import { useState } from "react";
import FrameworkFlow from "./components/FrameworkFlow.jsx";
import MetricsPanel from "./components/MetricsPanel.jsx";
import PrototypeWorkspace from "./components/PrototypeWorkspace.jsx";

const tabs = [
  { id: "prototype", label: "Prototype Workspace" },
  { id: "framework", label: "A²V Workflow" },
  { id: "metrics", label: "Metrics & Selection" },
];

export default function App() {
  const [activeTab, setActiveTab] = useState("prototype");

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <h1>A²V-SQL Prototype System</h1>
          <p>Interactive research prototype for schema grounding, validation, repair and EASE final selection.</p>
        </div>
        <div className="status-pill">Research prototype</div>
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
        {activeTab === "prototype" && <PrototypeWorkspace />}
        {activeTab === "framework" && <FrameworkFlow />}
        {activeTab === "metrics" && <MetricsPanel />}
      </main>
    </div>
  );
}
