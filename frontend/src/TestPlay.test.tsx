import {render,screen,cleanup,fireEvent} from '@testing-library/react';
import {afterEach,it,expect,vi} from 'vitest';
import TestPlay from './TestPlay';
afterEach(()=>{cleanup();localStorage.clear();vi.unstubAllGlobals();});
it('keeps a lost command across reload and retries its original identity',async()=>{
  const body={session_id:'saved',command:{command_id:'original',expected_revision:0,command:{kind:'skip_ultimate'}}};
  localStorage.setItem('graytower.planner-test-session','saved');
  localStorage.setItem('graytower.planner-test-pending',JSON.stringify(body));
  const calls:unknown[]=[];
  const view={session_id:'saved',revision:1,play_configuration:{breaker_multiplier:1.6},observation:{phase:'ordinary',actor_id:'breaker_01',state:{skill_points:3,units:{}},legal_commands:[]}};
  vi.stubGlobal('fetch',vi.fn(async (_url:string,init?:RequestInit)=>{if(init?.body)calls.push(JSON.parse(String(init.body)));return {ok:true,json:async()=>view} as Response;}));
  render(<TestPlay/>);
  const retry=await screen.findByRole('button',{name:'查询／重试刚才的同一个行动'});
  fireEvent.click(retry);
  await screen.findByText('轮到击破手行动');
  expect(calls).toEqual([body]);
});
