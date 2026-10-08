import {cleanup,render,screen} from '@testing-library/react';
import {afterEach,it,expect,vi} from 'vitest';
import CodeRepair from './CodeRepair';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('reads a real-record shape without triggering models and states the exact test scope',async()=>{
  const calls:string[]=[];
  vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
    expect(init?.method).toBeUndefined();calls.push(url);
    return {ok:true,json:async()=>({available:true,request:'护盾抵消后仍扣血',candidate_id:'a'.repeat(64),
      patch:'-hp_loss=min(u.hp,amount)\n+hp_loss=min(u.hp,left)',summary:'将生命扣减改为剩余伤害。',review:'Review opinion',
      baseline_tests:[{name:'完全吸收',status:'FAIL'}],candidate_tests:[{name:'完全吸收',status:'PASS'}],
      calls:7,cost_usd:'0.013317168',autonomous_children:0})} as Response;
  }));
  render(<CodeRepair/>);
  await screen.findByText('将生命扣减改为剩余伤害。');
  expect(screen.getByText(/尚未接入统一代码 QA Agent/)).toBeTruthy();
  expect(screen.getByText(/没有自主委派子任务/)).toBeTruthy();
  expect(calls).toEqual(['/api/code-demo']);
});
