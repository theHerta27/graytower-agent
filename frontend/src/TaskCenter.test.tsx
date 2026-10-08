import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import TaskCenter from './TaskCenter';

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('links a selected candidate without copying hashes and distinguishes test approval from application', async () => {
  const hash = 'a'.repeat(64);
  const candidate = { manifest_hash: hash, request: '真实历史候选', confirmed: false,
    diff: [{ path: 'skills.breaker_skill.multiplier', before: 1.4, after: 1.6 }], validation: { passed: true } };
  let created: unknown;
  const task = { task_id: 'new1', kind: 'config', request: '任务需求', status: 'awaiting_test_approval',
    candidate_id: hash, candidate, origin: 'existing_candidate', events: [], report: null, applied: false };
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === '/api/tasks' && init?.method === 'POST') {
      created = JSON.parse(String(init.body)); return new Response(JSON.stringify(task));
    }
    if (url === '/api/tasks') return new Response(JSON.stringify({ tasks: created ? [task] : [] }));
    if (url === '/api/candidates') return new Response(JSON.stringify({ candidates: [candidate] }));
    return new Response(JSON.stringify(task));
  }));
  render(<TaskCenter status={{ profile: 'trusted-combat-numeric-v1', model: { enabled: false, remaining_calls: 0, reason: '关闭' } }} />);
  await screen.findByText('真实历史候选');
  fireEvent.change(screen.getByLabelText('研发需求'), { target: { value: '任务需求' } });
  fireEvent.change(screen.getByLabelText('候选来源'), { target: { value: hash } });
  fireEvent.click(screen.getByRole('button', { name: '创建任务' }));
  await waitFor(() => expect(created).toMatchObject({ candidate_id: hash, request: '任务需求' }));
  expect(await screen.findByText('批准进入测试')).toBeTruthy();
  expect(screen.getByRole('link', { name: '下载 Excel' }).getAttribute('href')).toContain('/export/xlsx');
  expect(screen.getByText(/尚未应用到游戏/)).toBeTruthy();
});

it('offers receipt/checkpoint recovery for admitted interrupted QA with no new model grant', async () => {
  const task = { task_id: 'recover1', kind: 'verification', request: '恢复任务', status: 'interrupted',
    origin: 'existing_candidate', candidate: null, applied: false, events: [],
    report: { request: { request_id: 'qa1', report: null } } };
  let resumed = false;
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url=String(input);
    if(url==='/api/tasks') return new Response(JSON.stringify({tasks:[task]}));
    if(url==='/api/candidates') return new Response(JSON.stringify({candidates:[]}));
    if(url==='/api/tasks/recover1/resume' && init?.method==='POST') resumed=true;
    return new Response('{}');
  }));
  render(<TaskCenter status={{profile:'test',model:{enabled:false,remaining_calls:0,reason:'关闭'}}}/>);
  fireEvent.click(await screen.findByRole('button',{name:/恢复任务.*等待人工恢复/}));
  fireEvent.click(await screen.findByRole('button',{name:'恢复已准入验证'}));
  await waitFor(()=>expect(resumed).toBe(true));
});
