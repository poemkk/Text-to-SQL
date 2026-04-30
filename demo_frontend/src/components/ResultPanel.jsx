export default function ResultPanel({ result }) {
  if (!result) {
    return (
      <section className="panel result-panel">
        <div className="section-heading">
          <h2>Execution Result</h2>
        </div>
        <p className="muted">No execution result yet.</p>
      </section>
    );
  }

  return (
    <section className="panel result-panel">
      <div className="section-heading">
        <h2>Execution Result</h2>
        <p>{result.exec_ok ? `${result.row_count} row(s)` : "Execution failed"}</p>
      </div>
      {!result.exec_ok && <div className="error-box">{result.error}</div>}
      {result.exec_ok && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {result.columns.map((column) => (
                  <th key={column}>{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex}>{String(cell)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
