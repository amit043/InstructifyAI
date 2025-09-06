import { useEffect, useState } from 'react';
import { apiFetch } from '../lib/api';

export interface ActiveLearningItem {
  chunk_id: string;
  reasons: string[];
}

export function useActiveLearningQueue(projectId: string, limit: number = 10) {
  const [items, setItems] = useState<ActiveLearningItem[]>([]);

  useEffect(() => {
    if (!projectId) return;
    apiFetch(`/curation/next?project_id=${projectId}&limit=${limit}`)
      .then((data: any) => setItems(data as ActiveLearningItem[]))
      .catch(() => setItems([]));
  }, [projectId, limit]);

  return items;
}
