let connection;
export function connect() {
  return connection ||= fetch('/api/workspace/status').then(async response => {
    if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) return null;
    const value = await response.json();
    return value.editable && value.token ? value : null;
  }).catch(() => null);
}
export async function request(route, data) {
  const session = await connect();
  if (!session) throw new Error('Start this repository with npm run dev to save changes locally.');
  const response = await fetch(`/api/workspace/${route}`, {
    method: data ? 'POST' : 'GET',
    headers: { 'X-Workspace-Token': session.token, ...(data ? {'Content-Type':'application/json'} : {}) },
    ...(data ? {body:JSON.stringify(data)} : {})
  });
  const result = await response.json();
  if (!response.ok) { const error = new Error(result.error || 'The operation failed.'); error.status = response.status; throw error; }
  return result;
}
