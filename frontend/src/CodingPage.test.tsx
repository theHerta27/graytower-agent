import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import CodingPage from './CodingPage';
import type { CodingRun } from './types';

const run: CodingRun = { operation_id: 'coding_saved', request: '把倍率改为 1.58', mode: 'auto', status: 'completed',
  stage: 'completed', error: null, manifest_hash: 'a'.repeat(64), summary: '仅修改了战技倍率。', review_text: '未发现意外改动。',
  spawned_thread_ids: [], spawn_attempts: 0, seconds: 29.344, budget: null };
const disabled = { enabled: false, remaining_calls: 0, reason: '本批授权已关闭。', modes: ['single', 'auto'] };
afterEach(() => { cleanup(); sessionStorage.clear(); vi.unstubAllGlobals(); });
const response = (value: unknown, ok = true) => ({ ok, status: ok ? 200 : 404, json: async () => value }) as Response;

describe('Coding workbench', () => {
  it('starts the exact authorized task ID and input instead of inventing a new one', async () => {
    const task = { operation_id: 'preauthorized', request: '固定原需求', mode: 'auto' as const }; const posts: unknown[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST') { posts.push(JSON.parse(String(init.body))); return response({ operation_id: task.operation_id, kind: 'coding', status: 'completed', result: {}, error: null }); }
      if (url.includes('/operations/')) return response({ operation_id: task.operation_id, kind: 'coding', status: 'completed', result: {}, error: null });
      return response({ runs: [] });
    }));
    render(<CodingPage status={{ ...disabled, enabled: true, remaining_calls: 8, tasks: [task] }} revision={0} onCandidate={vi.fn()} />);
    await screen.findByDisplayValue('固定原需求');
    fireEvent.click(screen.getByRole('button', { name: '开始文件任务' }));
    await waitFor(() => expect(posts).toEqual([task]));
  });
  it('opens a saved candidate without confirming or running models and distinguishes allowed from actual collaboration', async () => {
    const reads: string[] = []; const open = vi.fn();
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      expect(init?.method).toBeUndefined(); reads.push(url);
      return response(url === '/api/coding/runs' ? { runs: [run] } : { run });
    }));
    render(<CodingPage status={disabled} revision={0} onCandidate={open} />);
    await screen.findByText('未发现意外改动。');
    expect(screen.getByText('自主委派 0 个子任务')).toBeTruthy();
    expect(screen.getByText('原生 Review 意见 · 不等于 QA 通过')).toBeTruthy();
    expect((screen.getByRole('button', { name: '开始文件任务' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: '核对这一候选' }));
    expect(open).toHaveBeenCalledWith(run.manifest_hash);
    expect(reads.every(url => url.startsWith('/api/coding/runs'))).toBe(true);
  });

  it('retains exact request and operation ID after a lost POST response and only retries explicitly', async () => {
    const payload = { id: 'coding_lost', request: '只改倍率', mode: 'single' as const };
    sessionStorage.setItem('graytower.coding-pending', JSON.stringify(payload));
    const posts: unknown[] = []; let posted = false;
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST') { posts.push(JSON.parse(String(init.body))); posted = true;
        return response({ operation_id: payload.id, kind: 'coding', status: 'completed', result: {}, error: null }); }
      if (url === '/api/operations/coding_lost') return posted
        ? response({ operation_id: payload.id, kind: 'coding', status: 'completed', result: {}, error: null })
        : response({ error: { code: 'not_found', message: '未找到。' } }, false);
      return response({ runs: [] });
    }));
    render(<CodingPage status={disabled} revision={0} onCandidate={vi.fn()} />);
    await screen.findByRole('button', { name: '按原内容重试文件任务' });
    expect(posts).toEqual([]);
    fireEvent.click(screen.getByRole('button', { name: '按原内容重试文件任务' }));
    await waitFor(() => expect(posts).toEqual([{ operation_id: payload.id, request: payload.request, mode: 'single' }]));
    await waitFor(() => expect(sessionStorage.getItem('graytower.coding-pending')).toBeNull());
  });
});
