import { useEffect, useState } from 'react';
import { ChunkList, Chunk } from '../components/ChunkList';
import { GuidelineSidebar } from '../components/GuidelineSidebar';
import { useHotkeys } from '../hooks/useHotkeys';
import { useUndo } from '../hooks/useUndo';
import { apiFetch, fetchGuidelines, logGuidelineUsage } from '../lib/api';

export default function Home() {
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [filter, setFilter] = useState('');
  const [guidelines, setGuidelines] = useState<any[]>([]);
  const history = useUndo<Chunk[]>([]);

  const docId = typeof window !== 'undefined'
    ? new URLSearchParams(window.location.search).get('doc') || ''
    : '';
  const projectId = typeof window !== 'undefined'
    ? new URLSearchParams(window.location.search).get('project') || ''
    : '';

  useEffect(() => {
    if (!docId) return;
    apiFetch(`/documents/${docId}/chunks`).then((data: any) => {
      setChunks(data.chunks);
      history.setState(data.chunks);
    });
  }, [docId]);

  useEffect(() => {
    if (!projectId) return;
    fetchGuidelines(projectId)
      .then((g: any[]) => {
        setGuidelines(g);
        logGuidelineUsage({ action: 'view' });
      })
      .catch(() => undefined);
  }, [projectId]);

  useHotkeys({
    'ctrl+z': history.undo,
    'ctrl+y': history.redo,
  });

  const filtered = chunks.filter(
    ch =>
      !filter ||
      JSON.stringify(ch).toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <div style={{ display: 'flex' }}>
      <div style={{ flex: 1 }}>
        <h1>Curation Lite</h1>
        <input
          placeholder="filter"
          value={filter}
          onChange={e => setFilter(e.target.value)}
        />
        <ChunkList chunks={filtered} onChange={setChunks} selection={history} />
      </div>
      <GuidelineSidebar guidelines={guidelines} />
    </div>
  );
}
