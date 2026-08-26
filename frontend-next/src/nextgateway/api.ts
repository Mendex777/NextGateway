export type Subscription = {
  id: string;
  name: string;
  remote_name?: string;
  enabled: boolean;
  nodes_count: number;
  update_interval: number;
  last_success?: string;
  last_error?: string;
  upload_bytes?: number;
  download_bytes?: number;
  total_bytes?: number;
  expires_at?: string;
  announcement?: string;
};

export type Node = {
  id: string;
  name: string;
  enabled: boolean;
  protocol: string;
  server: string;
  port: number;
  source: string;
  last_latency_ms?: number;
  last_probe_error?: string;
};

export type AuthState = {
  setup_required: boolean;
  authenticated: boolean;
  username?: string;
  csrf_token?: string;
};

let csrfToken = '';

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body) headers.set('Content-Type', 'application/json');
  if (csrfToken && options.method && options.method !== 'GET') {
    headers.set('X-CSRF-Token', csrfToken);
  }
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    headers,
    credentials: 'same-origin',
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }));
    throw new Error(body.detail || `HTTP ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function loadAuth() {
  const state = await api<AuthState>('/auth/status');
  csrfToken = state.csrf_token || '';
  return state;
}

export async function login(username: string, password: string) {
  const state = await api<AuthState>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
  csrfToken = state.csrf_token || '';
  return state;
}

export async function logout() {
  await api<void>('/auth/logout', { method: 'POST' });
  csrfToken = '';
}

export function formatBytes(value = 0) {
  if (!value) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const exponent = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  const amount = value / 1024 ** exponent;
  return `${amount >= 10 ? amount.toFixed(1) : amount.toFixed(2)} ${units[exponent]}`;
}
