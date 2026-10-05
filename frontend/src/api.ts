import type { Candidate, Operation, RequestDetail, RequestSummary, Status, Trace } from './types';

export class ApiError extends Error {
  constructor(message: string, public code: string, public status: number) { super(message); }
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, body === undefined ? undefined : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
  } catch { throw new ApiError('无法连接本地服务。请确认服务已启动，再重试读取。', 'connection_failed', 0); }
  let payload: unknown;
  try { payload = await response.json(); }
  catch { throw new ApiError('本地服务返回了无法读取的内容。请检查服务状态。', 'invalid_response', response.status); }
  if (!response.ok) {
    const error = (payload as { error?: { message?: string; code?: string } }).error;
    throw new ApiError(error?.message || `读取失败（${response.status}）。`, error?.code || 'request_failed', response.status);
  }
  return payload as T;
}
const part = encodeURIComponent;
export const api = {
  status: () => request<Status>('/status'),
  candidates: () => request<{ candidates: Candidate[] }>('/candidates'),
  inspect: (hash: string) => request<Candidate>('/candidates/inspect', { manifest_hash: hash }),
  confirm: (hash: string) => request<Candidate>(`/candidates/${part(hash)}/confirm`, {}),
  requests: () => request<{ requests: RequestSummary[] }>('/requests'),
  detail: (id: string) => request<RequestDetail>(`/requests/${part(id)}`),
  trace: (id: string, hash: string) => request<Trace>(`/requests/${part(id)}/traces/${part(hash)}`),
  draft: (id: string, text: string) => request<Operation>('/drafts', { operation_id: id, request: text, parent_manifest: null }),
  operation: (id: string) => request<Operation>(`/operations/${part(id)}`),
  verify: (id: string, hash: string, goal: string, budget: number) => request<Operation>('/verifications', { request_id: id, manifest_hash: hash, goal, max_battles: budget }),
  resume: (id: string) => request<Operation>(`/verifications/${part(id)}/resume`, {}),
};
export function errorMessage(error: unknown) { return error instanceof Error ? error.message : '操作未完成，请重新读取状态。'; }
