import {fireEvent,render,screen} from '@testing-library/react';
import {expect,it,vi} from 'vitest';
import GitDeliveryPanel from './GitDeliveryPanel';

const ready={preparation_id:'prep1',approval_hash:'approval1',kind:'merge',state:'prepared',target_branch:'main',
  target_commit:'before',candidate_commit:'candidate',merge_commit:'merged',patch:'+fixed',changed_files:['rules.py'],
  can_approve:true,checks:[],worktree_path:'D:/task/delivery',note:'准备完成',stale_reason:null};

it('confirms exactly the displayed approval and closes when it changes',()=>{
  const action=vi.fn();
  const {rerender}=render(<GitDeliveryPanel delivery={ready} blocked={false} archived={false} onAction={action}/>);
  fireEvent.click(screen.getByRole('button',{name:'审阅并合入'}));
  expect(screen.getByRole('button',{name:'确认合入这个 Git 提交'})).toBeTruthy();
  rerender(<GitDeliveryPanel delivery={{...ready,approval_hash:'approval2'}} blocked={false} archived={false} onAction={action}/>);
  expect(screen.queryByRole('button',{name:'确认合入这个 Git 提交'})).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'审阅并合入'}));
  fireEvent.click(screen.getByRole('button',{name:'确认合入这个 Git 提交'}));
  expect(action).toHaveBeenCalledWith('delivery-approve',{preparation_id:'prep1',approval_hash:'approval2'});
});

it('shows the conflict directory and never offers approval until checks pass',()=>{
  render(<GitDeliveryPanel delivery={{...ready,state:'conflict',can_approve:false,conflicts:['rules.py']}} blocked={false} archived={false} onAction={vi.fn()}/>);
  expect(screen.getByText('D:/task/delivery')).toBeTruthy();
  expect(screen.getByRole('button',{name:'检查冲突处理结果'})).toBeTruthy();
  expect(screen.queryByRole('button',{name:'审阅并合入'})).toBeNull();
});
