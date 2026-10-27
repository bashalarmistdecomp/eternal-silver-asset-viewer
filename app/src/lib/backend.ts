// Where the Python backend is, and how to talk to it.
//
// In the desktop app the Rust shell (src-tauri/src/backend.rs) starts the
// backend and reports its port and token through `backend_state`. In a plain
// browser — developing the UI with `npm run dev` against `npm run backend`
// (backend/server.py on port 8765, token "dev") — they come from the URL
// (?backend=…&token=…) or from VITE_BACKEND / VITE_TOKEN.

import { invoke, isTauri } from '@tauri-apps/api/core'

export type BackendState =
  | { state: 'starting' }
  | { state: 'ready'; port: number; token: string; library: string }
  | { state: 'error'; message: string; log: string[] }

let base = ''
let token = ''

export const inTauri = isTauri()

function browserState(): BackendState {
  const q = new URLSearchParams(window.location.search)
  const url = q.get('backend') ?? import.meta.env.VITE_BACKEND ?? 'http://127.0.0.1:8765'
  const tok = q.get('token') ?? import.meta.env.VITE_TOKEN ?? 'dev'
  const port = Number(new URL(url).port || 80)
  return { state: 'ready', port, token: tok, library: '' }
}

function adopt(s: BackendState): BackendState {
  if (s.state === 'ready') {
    base = inTauri ? `http://127.0.0.1:${s.port}` : browserBase()
    token = s.token
  }
  return s
}

function browserBase(): string {
  const q = new URLSearchParams(window.location.search)
  return (q.get('backend') ?? import.meta.env.VITE_BACKEND ?? 'http://127.0.0.1:8765').replace(/\/$/, '')
}

/** How long to wait for the shell to say how the start went. The shell
 *  gives up itself after 90 s (backend.rs, START_TIMEOUT), saying why with
 *  the backend's log; a first start of a release build can take most of
 *  that (its runtime unpacked, then scanned), so the page waits longer. */
const CONNECT_TIMEOUT_MS = 120_000

/** Wait for the shell to finish starting the backend (or to fail to). */
export async function connect(): Promise<BackendState> {
  if (!inTauri) return adopt(browserState())
  const deadline = Date.now() + CONNECT_TIMEOUT_MS
  while (Date.now() < deadline) {
    const s = await invoke<BackendState>('backend_state')
    if (s.state !== 'starting') return adopt(s)
    await new Promise((r) => setTimeout(r, 100))
  }
  return { state: 'error', message: 'The backend did not start within two minutes.', log: [] }
}

/** Serve another library folder (null: the default one); the shell restarts the backend on it. */
export async function setLibrary(path: string | null): Promise<BackendState> {
  await invoke('set_library', { path })
  return connect()
}

export async function restartBackend(): Promise<BackendState> {
  await invoke('restart_backend')
  return connect()
}

export class ApiError extends Error {
  status: number
  extra: Record<string, unknown>
  constructor(status: number, message: string, extra: Record<string, unknown> = {}) {
    super(message)
    this.status = status
    this.extra = extra
  }
}

function withToken(path: string, params?: Record<string, string | number | undefined | null>): string {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params ?? {})) if (v !== undefined && v !== null) q.set(k, String(v))
  q.set('token', token)
  return `${base}${path}?${q}`
}

export function blobUrl(id: string, ext: string): string {
  return withToken(`/api/blob/${id}.${ext}`)
}

/** A binary reply and its headers (the music's PCM). */
export async function requestBytes(
  path: string,
  params?: Record<string, string | number | undefined | null>,
): Promise<{ data: ArrayBuffer; headers: Headers }> {
  let res: Response
  try {
    res = await fetch(withToken(path, params))
  } catch (e) {
    throw new ApiError(0, `The backend is not answering (${e instanceof Error ? e.message : String(e)}).`)
  }
  if (!res.ok) {
    let d: { error?: string } & Record<string, unknown> = {}
    try {
      d = (await res.json()) ?? {}
    } catch {
      // not JSON
    }
    throw new ApiError(res.status, d.error ?? `HTTP ${res.status}`, d)
  }
  return { data: await res.arrayBuffer(), headers: res.headers }
}

export async function request<T>(
  method: 'GET' | 'POST' | 'DELETE',
  path: string,
  body?: unknown,
  params?: Record<string, string | number | undefined | null>,
): Promise<T> {
  let res: Response
  try {
    res = await fetch(withToken(path, params), {
      method,
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch (e) {
    throw new ApiError(0, `The backend is not answering (${e instanceof Error ? e.message : String(e)}).`)
  }
  return reply<T>(res)
}

/** Bytes sent (a picture the app drew), a JSON reply. */
export async function postBytes<T>(path: string, data: Blob, params?: Record<string, string | number | undefined | null>): Promise<T> {
  let res: Response
  try {
    res = await fetch(withToken(path, params), { method: 'POST', headers: { 'Content-Type': data.type || 'application/octet-stream' }, body: data })
  } catch (e) {
    throw new ApiError(0, `The backend is not answering (${e instanceof Error ? e.message : String(e)}).`)
  }
  return reply<T>(res)
}

async function reply<T>(res: Response): Promise<T> {
  const text = await res.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    throw new ApiError(res.status, `Unexpected reply from the backend: ${text.slice(0, 200)}`)
  }
  if (!res.ok) {
    const d = (data ?? {}) as { error?: string } & Record<string, unknown>
    throw new ApiError(res.status, d.error ?? `HTTP ${res.status}`, d)
  }
  return data as T
}
