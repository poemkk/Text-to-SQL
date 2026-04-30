export default function ValidationPanel({ title, steps, tone = "blue" }) {
  return (
    <section className={`panel validation-panel ${tone}`}>
      <div className="section-heading">
        <h2>{title}</h2>
      </div>
      <div className="mini-flow">
        {steps.map((step, index) => (
          <div key={step} className="mini-step">
            <span>{index + 1}</span>
            <strong>{step}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}
