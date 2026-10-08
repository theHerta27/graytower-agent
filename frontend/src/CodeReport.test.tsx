import {cleanup,render,screen} from '@testing-library/react';
import {afterEach,expect,it} from 'vitest';
import ReportView from './ReportView';
import type {RequestDetail} from './types';
afterEach(cleanup);
it('explains code checks in ordinary Chinese without presenting them as battles',()=>{
  const detail={request:{request_id:'qa',manifest_hash:'a'.repeat(64),goal:'检查护盾',status:'completed',charged_battles:2,max_battles:2,
    report:{kind:'code',verdict:'PASS',summary:'护盾修复通过本次检查',test_labels:['护盾完全吸收'],jobs:[
      {job_id:'old',args:{variant:'baseline'},result:{tests:[{name:'shield',status:'FAIL'}]}},
      {job_id:'new',args:{variant:'candidate'},result:{tests:[{name:'shield',status:'PASS'}]}}],limitations:['仅检查护盾规则']}},
    facts:null,report_text:null} as unknown as RequestDetail;
  render(<ReportView detail={detail}/>);
  expect(screen.getByText('护盾完全吸收')).toBeTruthy();
  expect(screen.getByText('原始故障版')).toBeTruthy();
  expect(screen.getByText('修复后的版本')).toBeTruthy();
  expect(screen.queryByText('这批战斗发生了什么')).toBeNull();
  expect(screen.getByText(/下一步/)).toBeTruthy();
});
