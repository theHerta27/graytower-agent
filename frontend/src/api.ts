import type { Candidate, CodingRun, Operation, RequestDetail, RequestSummary, Status, Trace } from './types';

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
import type { TaskRecord } from './types';
export const api = {
  taskList: () => request<{ tasks: TaskRecord[] }>('/tasks'),
  taskCreate: (body: { task_id: string; kind: string; request: string; candidate_id: string | null; coding_operation_id?:string|null }) => request<TaskRecord>('/tasks', body),
  taskReplay:(id:string,task_id:string)=>request<TaskRecord>(`/tasks/${part(id)}/replay`,{task_id}),
  taskAdopt:(id:string,operation_id:string,accept_sample:boolean)=>request(`/tasks/${part(id)}/adopt`,{operation_id,accept_sample}),
  releaseRollback:(kind:string,operation_id:string)=>request(`/releases/${part(kind)}/rollback`,{operation_id}),
  releases:()=>request<Record<string,{active_release:string;version?:{candidate_id:string;release_id:string}|null}>>('/releases'),
  taskGenerate: (id: string) => request<Operation>(`/tasks/${part(id)}/generate`, {}),
  taskResume: (id: string) => request<Operation>(`/tasks/${part(id)}/resume`, {}),
  taskApprove: (id: string) => request<TaskRecord>(`/tasks/${part(id)}/approve-test`, {}),
  taskHistory: (id: string, request_id: string) => request<TaskRecord>(`/tasks/${part(id)}/history`, { request_id }),
  taskVerify: (id: string, goal: string, budget: number) => request<Operation>(`/tasks/${part(id)}/verify`, { goal, max_battles: budget }),
  status: () => request<Status>('/status'),
  codingRuns: () => request<{ runs: CodingRun[] }>('/coding/runs'),
  codingRun: (id: string) => request<{ run: CodingRun }>(`/coding/runs/${part(id)}`),
  codingStart: (id: string, text: string, mode: 'single' | 'auto') => request<Operation>('/coding/runs', { operation_id: id, request: text, mode }),
  codingResume: (id: string) => request<Operation>(`/coding/runs/${part(id)}/resume`, {}),
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
