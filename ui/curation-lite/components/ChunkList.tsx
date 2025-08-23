import { useState } from 'react';
import { bulkApply } from '../lib/api';
import { ChunkEditor } from './ChunkEditor';

export interface Chunk {
  id: string;
  order?: number;
  content: any;
  metadata: any;
  rev: number;
}

interface Props {
  chunks: Chunk[];
  onChange(chunks: Chunk[]): void;
  selection: { state: Chunk[]; setState(chunks: Chunk[]): void };
}

export function ChunkList({ chunks, onChange, selection }: Props) {
  const [selected, setSelected] = useState<string[]>([]);

  const updateChunk = (id: string, meta: any) => {
    const next = chunks.map(ch => (ch.id === id ? { ...ch, metadata: meta } : ch));
    onChange(next);
    selection.setState(next);
  };

  const applyBulk = async () => {
    if (selected.length === 0) return;
    await bulkApply({
      selection: { chunk_ids: selected },
      patch: { metadata: { reviewed: true } },
    });
  };

  return (
    <div>
      {chunks.map(ch => (
        <div key={ch.id} style={{ borderBottom: '1px solid #ccc' }}>
          <label>
            <input
              type="checkbox"
              checked={selected.includes(ch.id)}
              onChange={e => {
                const next = e.target.checked
                  ? [...selected, ch.id]
                  : selected.filter(id => id !== ch.id);
                setSelected(next);
              }}
            />
            Chunk {ch.order ?? ch.id}
          </label>
          <ChunkEditor chunk={ch} onChange={meta => updateChunk(ch.id, meta)} />
        </div>
      ))}
      <button onClick={applyBulk}>Bulk Apply Reviewed</button>
    </div>
  );
}
