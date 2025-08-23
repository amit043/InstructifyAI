export async function apiFetch(path: string, init: RequestInit = {}) {
  const token = typeof window !== 'undefined' ? localStorage.getItem('jwt') : null;
  const headers = {
    ...(init.headers || {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  } as Record<string, string>;
  const resp = await fetch(path, { ...init, headers });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const ct = resp.headers.get('content-type') || '';
  if (ct.includes('application/json')) {
    return resp.json();
  }
  return resp.text();
}

export function bulkApply(payload: any) {
  return apiFetch('/chunks/bulk-apply', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...payload, user: payload.user || 'dev' }),
  });
}

export function acceptSuggestion(chunkId: string, field: string, user: string) {
  return apiFetch(`/chunks/${chunkId}/suggestions/${field}/accept`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user }),
  });
}

export function fetchGuidelines(projectId: string) {
  return apiFetch(`/projects/${projectId}/taxonomy/guidelines`);
}

export function logGuidelineUsage(event: { action: string; field?: string }) {
  return apiFetch('/guidelines/usage', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(event),
  }).catch(() => undefined);
}
