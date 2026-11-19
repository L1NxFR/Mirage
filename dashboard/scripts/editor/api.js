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
  if (!session) throw new Error('请在本项目中运行 npm run dev，以保存到本地文件。');
  const response = await fetch(`/api/workspace/${route}`, {
    method: data ? 'POST' : 'GET',
    headers: { 'X-Workspace-Token': session.token, ...(data ? {'Content-Type':'application/json'} : {}) },
    ...(data ? {body:JSON.stringify(data)} : {})
  });
  const result = await response.json();
  if (!response.ok) { const error = new Error(result.error || '操作失败。'); error.status = response.status; throw error; }
  return result;
}
