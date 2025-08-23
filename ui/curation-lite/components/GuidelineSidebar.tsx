interface GuidelineField {
  field: string;
  helptext?: string;
  examples?: string[];
}

interface Props {
  guidelines: GuidelineField[];
}

export function GuidelineSidebar({ guidelines }: Props) {
  return (
    <aside
      style={{
        width: '25%',
        padding: '1rem',
        borderLeft: '1px solid #ccc',
        overflowY: 'auto',
        height: '100vh',
      }}
    >
      <h2>Guidelines</h2>
      {guidelines.map(g => (
        <div key={g.field} style={{ marginBottom: '1rem' }}>
          <strong>{g.field}</strong>
          {g.helptext && <p>{g.helptext}</p>}
          {g.examples && g.examples.length > 0 && (
            <ul>
              {g.examples.map((ex, i) => (
                <li key={i}>{ex}</li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </aside>
  );
}
