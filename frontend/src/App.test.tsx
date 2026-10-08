import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';

// Engineering fixtures for UI behavior only. These are not game/model acceptance evidence.
const manifest = 'a'.repeat(64);
const candidate = {
  manifest_hash: manifest, request: '把击破手战技倍率改为1.6。', confirmed: false,
  diff: [{ path: 'skills.breaker_skill.multiplier', before: 1.4, after: 1.6 }],
  validation: { passed: true, layers: { schema: { passed: true, errors: [] } } },
};
const request = { request_id: 'engineering-ui', manifest_hash: manifest, goal: '比较胜负和行动值', status: 'completed', charged_battles: 4, max_battles: 4, verdict: 'INCONCLUSIVE' };
const detail = {
  request: { ...request, report: {
    verdict: 'INCONCLUSIVE', structural_verdict: 'PASS', summary: '只有固定样本观测。',
    agent_decision_note: '模型声称已证实全面改善。', errors: ['ValueError: invalid policy'],
    limitations: ['尚不能保证总体改善。'], observations: [], jobs: [{ job_id: 'job-ui', result: { rows: [{ policy: 'balanced', seed: 7, baseline: { outcome: 'win', trace_sha256: 'b'.repeat(64) }, candidate: { outcome: 'loss', trace_sha256: 'c'.repeat(64) } }] } }],
  } },
  facts: { verdict: 'INCONCLUSIVE', distinct_pairs: 2, comparisons: [{ policy: 'balanced', seed: 11, baseline_av: '16000/7', candidate_av: '2200', delta_av: '-600/7', direction: '行动值减少' }], transitions: { 'balanced:win->loss': 1, 'balanced:win->win': 1 }, original_error_count: 1, basis: '程序精确计算。', meaning: '行动值较少表示更早结束。', limit: '不能证明总体改善。', model_text_status: '模型自然语言说明为未核验草稿。' },
  report_text: '工程测试报告',
};
let calls: { url: string; method: string }[];

beforeEach(() => {
  calls = [];
  sessionStorage.clear();
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input); const method = init?.method || 'GET';
    calls.push({ url, method });
    let body: unknown;
    if (url === '/api/status') body = { model: { enabled: false, remaining_calls: 0, reason: '本批模型调用额度已用尽。' }, profile: 'test-only' };
    else if (url === '/api/tasks') body = { tasks: [] };
    else if (url === '/api/candidates') body = { candidates: [candidate] };
    else if (url === '/api/candidates/inspect') body = candidate;
    else if (url.endsWith('/confirm')) body = { ...candidate, confirmed: true };
    else if (url === '/api/requests') body = { requests: [request] };
    else if (url.includes('/traces/')) body = { excerpt: JSON.stringify({ events: [{ event_id: 'event_0001', kind: 'battle_finished', av: '2200', payload: { outcome: 'loss' } }] }), selection: { selected_events: 1, total_events: 8, limit: '这是单个版本的部分事件摘录，不能证明因果关系。' }, reference: { variant: 'candidate', seed: 7, policy: 'balanced' } };
    else if (url === '/api/requests/engineering-ui') body = detail;
    else throw new Error(`Unexpected request ${method} ${url}`);
    return { ok: true, status: 200, json: async () => body } as Response;
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('workbench public workflow', () => {
  it('opens the task center from the shared navigation', async () => {
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: /任务中心/ }));
    expect(await screen.findByLabelText('研发需求')).toBeTruthy();
  });
  it('retries a lost submission with the same ID and frozen payload after reload', async () => {
    const pending = { id: 'draft_lost', kind: 'draft', payload: { request: '改为1.6' } };
    sessionStorage.setItem('graytower.pending-operation', JSON.stringify(pending));
    const normalFetch = globalThis.fetch;
    let posted = false;
    const submissions: unknown[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === '/api/operations/draft_lost') {
        return { ok: posted, status: posted ? 200 : 404, json: async () => posted
          ? { operation_id: 'draft_lost', kind: 'draft', status: 'completed', result: { status: 'needs_input', message: '请明确目标。' }, error: null }
          : { error: { code: 'not_found', message: '未找到该记录。' } } } as Response;
      }
      if (String(input) === '/api/drafts') {
        submissions.push(JSON.parse(String(init?.body))); posted = true;
        return { ok: true, status: 202, json: async () => ({ operation_id: 'draft_lost', kind: 'draft', status: 'running', result: null, error: null }) } as Response;
      }
      return normalFetch(input, init);
    }));
    render(<App />);
    fireEvent.click(await screen.findByRole('button', { name: '按原内容重试提交' }, { timeout: 2500 }));
    await screen.findByText('请明确目标。', {}, { timeout: 3500 });
    expect(submissions).toEqual([{ operation_id: 'draft_lost', request: '改为1.6', parent_manifest: null }]);
    expect(sessionStorage.getItem('graytower.pending-operation')).toBeNull();
  });

  it('refresh retries a failed report read even when the selected request is unchanged', async () => {
    const normalFetch = globalThis.fetch; let reads = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === '/api/requests/engineering-ui' && reads++ === 0) throw new Error('offline');
      return normalFetch(input, init);
    }));
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: '独立验证' }));
    await screen.findByText('无法连接本地服务。请确认服务已启动，再重试读取。');
    fireEvent.click(screen.getAllByRole('button', { name: '刷新数据' })[0]);
    await screen.findByRole('heading', { name: '尚不足以判断总体效果' });
    expect(reads).toBe(2);
  });

  it('explains the model lock and never submits a disabled generation', async () => {
    render(<App />);
    await screen.findByText('本批模型调用额度已用尽。');
    fireEvent.change(screen.getByLabelText('想调整什么'), { target: { value: '改为1.6' } });
    const generate = screen.getByRole('button', { name: '生成候选提案' }) as HTMLButtonElement;
    expect(generate.disabled).toBe(true);
    fireEvent.click(generate);
    expect(calls.filter(call => call.method === 'POST')).toEqual([]);
  });

  it('requires a separate explicit confirmation for the selected frozen candidate', async () => {
    render(<App />);
    await screen.findByText('把击破手战技倍率改为1.6。');
    expect(calls.some(call => call.url.endsWith('/confirm'))).toBe(false);
    fireEvent.click(screen.getByLabelText('我已核对以上变更，批准进入测试'));
    fireEvent.click(screen.getByRole('button', { name: '批准进入测试' }));
    await screen.findByText('已批准进入测试，可以交给独立验证。');
    expect(calls.filter(call => call.url.endsWith('/confirm'))).toEqual([{ url: `/api/candidates/${manifest}/confirm`, method: 'POST' }]);
  });

  it('separates overall uncertainty, structural checks, facts, errors and unverified prose; opens scoped evidence', async () => {
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: '独立验证' }));
    await screen.findByRole('heading', { name: '尚不足以判断总体效果' });
    expect(screen.getByText('结构检查通过')).toBeTruthy();
    expect(screen.getByText('胜利 → 失败')).toBeTruthy();
    expect(screen.getByText('行动值减少')).toBeTruthy();
    expect(screen.getByText('-600/7')).toBeTruthy();
    expect(screen.getByText('ValueError: invalid policy')).toBeTruthy();
    expect(screen.getByText('模型意见 · 未核验')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '查看候选记录 · 样本7' }));
    await screen.findByText('这是单个版本的部分事件摘录，不能证明因果关系。');
    await waitFor(() => expect(calls.some(call => call.url.includes('/traces/'))).toBe(true));
  });
});
