import { acceptSuggestion } from '../lib/api';

interface Props {
  chunk: any;
  onChange(meta: any): void;
}

export function ChunkEditor({ chunk, onChange }: Props) {
  const meta = { ...chunk.metadata };
  const suggestions = meta.suggestions || {};

  const handleChange = (field: string, value: string) => {
    const newMeta = { ...meta, [field]: value };
    onChange(newMeta);
  };

  return (
    <div style={{ marginLeft: '1rem' }}>
      <pre style={{ whiteSpace: 'pre-wrap' }}>{chunk.content?.text}</pre>
      {Object.entries(meta)
        .filter(([k]) => k !== 'suggestions')
        .map(([field, value]) => (
          <div key={field}>
            <label>{field}</label>
            <input
              value={String(value)}
              onChange={e => handleChange(field, e.target.value)}
            />
          </div>
        ))}
      {Object.entries(suggestions).map(([field, s]: any) => (
        <div key={field} style={{ marginTop: '0.5rem' }}>
          <button
            onClick={() => {
              handleChange(field, s.value);
              acceptSuggestion(chunk.id, field, 'dev');
            }}
          >
            Accept {field}: {String(s.value)}
          </button>
          {s.rationale && (
            <div style={{ fontSize: '0.8em', color: '#555' }}>
              Why: {s.rationale}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
