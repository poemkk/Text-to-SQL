export default function RepairPanel({ repair, error }) {
  return (
    <section className="panel repair-panel">
      <div className="section-heading">
        <h2>Error-feedback Repair</h2>
      </div>
      {error && <div className="error-box">{error}</div>}
      {repair ? (
        <div className="repair-details">
          <div>
            <span className="label">Repair attempted</span>
            <strong>{repair.repair_attempted ? "true" : "false"}</strong>
          </div>
          <div>
            <span className="label">Reason</span>
            <p>{repair.repair_reason}</p>
          </div>
          {repair.repaired_sql && (
            <pre className="code-block small">{repair.repaired_sql}</pre>
          )}
          {"exec_ok" in repair && (
            <div className={repair.exec_ok ? "success-box" : "error-box"}>
              {repair.exec_ok ? "Re-validation passed" : repair.exec_error || "Re-validation failed"}
            </div>
          )}
          {"final_pass" in repair && (
            <div className={repair.final_pass ? "success-box" : "error-box"}>
              {repair.final_pass ? "Final pass: true" : "Final pass: false"}
            </div>
          )}
        </div>
      ) : (
        <p className="muted">No repair result yet.</p>
      )}
    </section>
  );
}
