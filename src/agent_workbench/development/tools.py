"""Runtime dynamic tools. The host owns paths, edits and physical execution."""
import json
import re
from .workspace import digest
from .sandbox import CHECK_SETS
from .scenario import scenario_script


def tool(name, description, properties, required=()):
    return {'type':'function','name':name, 'description':description, 'inputSchema':{
        'type':'object','properties':properties,'required':list(required),'additionalProperties':False}}


TEXT={'type':'string','minLength':1,'maxLength':250}
TOOL_SPECS=[
    tool('project_status','查看当前项目版本、候选文件、真实Diff与已有检查。范围校验不等于测试通过。',{}),
    tool('read_file','只读候选源码或规则，正文按字节分页。返回文件SHA与实际行段，按next_line/next_column继续；长行的start_column从0计。',
         {'path':TEXT,'start_line':{'type':'integer','minimum':1},'start_column':{'type':'integer','minimum':0},'max_lines':{'type':'integer','minimum':1,'maximum':400}},['path']),
    tool('search_code','在允许的游戏材料内做不区分大小写的文字检索，返回文件与行号。',
         {'query':{'type':'string','minLength':1,'maxLength':200}},['query']),
    tool('write_file','仅修改隔离候选源码/配置。先读取SHA；新增用null SHA，删除用null content。可信回归与原项目不可修改。',
         {'path':TEXT,'expected_sha256':{'type':['string','null'],'pattern':'^[a-f0-9]{64}$'},
          'content':{'type':['string','null'],'maxLength':500000}},['path','expected_sha256','content']),
    tool('replace_text','在当前SHA对应文件中精确替换一处文本；old_text必须恰好匹配一次。优先用此工具做局部修复，避免重写整个文件。',
         {'path':TEXT,'expected_sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'},
          'old_text':{'type':'string','minLength':1,'maxLength':24000},
          'new_text':{'type':'string','maxLength':24000}},['path','expected_sha256','old_text','new_text']),
    tool('start_check','开始可信回归并立即返回Job。稍后read_check读取结果；修改后应重新检查，旧结果不能证明新候选。',
         {'check_set':{'type':'string','enum':list(CHECK_SETS)}},['check_set']),
    tool('read_check','读取已有Job的真实结果。running请稍后再读；unknown不自动重跑；不得把模型判断当测试结果。',
         {'job_id':{'type':'string','pattern':'^[a-f0-9]{64}$'}},['job_id']),
    tool('start_diagnostic','在同样受限容器内执行临时Python探索，帮助调查实际规则；仅算观察，不能代替可信回归。',
         {'python':{'type':'string','minLength':1,'maxLength':8000}},['python']),
]
SCHEMAS={t['name']:t['inputSchema'] for t in TOOL_SPECS}

SCENARIO_TOOL=tool('run_scenario',
    '在真实候选中观察小段规则行动的前后状态、事件和异常，返回后台Job，随后read_check读取。仅OBSERVATION，不是验收。'
    'scenario_json对象可含initial_skill_points(0..9)、skill_points_max(1..9)、最多4个shields({target_id,value,duration})和最多8个actions。'
    'actions为{kind:resource,gained:int,spent:int}、{kind:skill,actor_id,skill_id,target_ids:[id]}或{kind:tick_status,actor_id}。ID先读当前配置。',
    {'scenario_json':{'type':'string','minLength':2,'maxLength':6000}},['scenario_json'])


def tool_specs(profile='standard'):
    if profile not in ('standard','game'):raise ValueError('unsupported tool profile')
    return [*TOOL_SPECS,*([SCENARIO_TOOL] if profile=='game' else [])]


def validate_arguments(args,schema):
    """Validate this fixed, flat tool catalog without expanding the SDK environment."""
    if not isinstance(args,dict) or set(args)-set(schema['properties']) or set(schema['required'])-set(args):
        raise ValueError('invalid tool arguments')
    for key,value in args.items():
        rule=schema['properties'][key]
        types=rule['type'] if isinstance(rule['type'],list) else [rule['type']]
        actual='null' if value is None else 'string' if isinstance(value,str) else 'integer' if type(value) is int else 'unsupported'
        if actual not in types:raise ValueError('invalid argument type: '+key)
        if value is None:continue
        if isinstance(value,str):
            if not rule.get('minLength',0)<=len(value)<=rule.get('maxLength',500000):raise ValueError('invalid argument length: '+key)
            if 'pattern' in rule and not re.fullmatch(rule['pattern'],value):raise ValueError('invalid argument format: '+key)
        if type(value) is int and not rule.get('minimum',value)<=value<=rule.get('maximum',value):raise ValueError('invalid range: '+key)
        if 'enum' in rule and value not in rule['enum']:raise ValueError('unsupported value: '+key)


class DevelopmentTools:
    def __init__(self,workspace,jobs,profile='standard'):
        self.workspace=workspace;self.jobs=jobs
        self.schemas={t['name']:t['inputSchema'] for t in tool_specs(profile)}

    def dispatch(self,name,args,operation):
        if name=='project_status':
            view=self.workspace.inspect()
            if len(view['patch'])>24000:
                view['patch']=view['patch'][:24000];view['patch_truncated']=True
            return {**view,'checks':self.jobs.list(self.workspace)}
        if name=='read_file':
            value=self.workspace.read_file(args['path'])
            lines=value.pop('text').splitlines(keepends=True)
            start=args.get('start_line',1);column=args.get('start_column',0);count=args.get('max_lines',200)
            if (start<1 or column<0 or count<1 or start>max(1,len(lines)) or
                    (lines and column>=len(lines[start-1])) or (not lines and column)):
                raise ValueError('source cursor is outside the file')
            result={**value,'text':'','start_line':start,'start_column':column,'end_line':0,'end_column':0,
                    'total_lines':len(lines),'next_line':None,'next_column':None,'truncated':False}
            # Budget serialized text (newlines, quotes and Unicode included),
            # leaving headroom for metadata. Never split a Unicode character.
            budget=4900-len(json.dumps(result,ensure_ascii=False).encode('utf-8'))
            pieces=[];next_line=start;next_column=column
            for index in range(start-1,min(len(lines),start-1+count)):
                offset=column if index==start-1 else 0;fragment=lines[index][offset:]
                length=len(json.dumps(fragment,ensure_ascii=False).encode('utf-8'))-2
                if length>budget:
                    low,high=0,len(fragment)
                    while low<high:
                        middle=(low+high+1)//2
                        if len(json.dumps(fragment[:middle],ensure_ascii=False).encode('utf-8'))-2<=budget:low=middle
                        else:high=middle-1
                    fragment=fragment[:low];length=len(json.dumps(fragment,ensure_ascii=False).encode('utf-8'))-2
                if not fragment:break
                pieces.append(fragment);budget-=length
                end_column=offset+len(fragment)
                result.update(end_line=index+1,end_column=end_column)
                next_line,next_column=(index+2,0) if end_column==len(lines[index]) else (index+1,end_column)
                if next_column or budget<=0:break
            result['text']=''.join(pieces)
            if lines and next_line<=len(lines):
                result.update(next_line=next_line,next_column=next_column,truncated=True)
            return result
        if name=='search_code':return self.workspace.search(args['query'])
        if name=='write_file':return self.workspace.write_file(operation,**args)
        if name=='replace_text':return self.workspace.replace_text(operation,**args)
        if name=='start_check':return self.jobs.start(self.workspace,args['check_set'])
        if name=='read_check':return self.jobs.read(args['job_id'],self.workspace)
        if name=='start_diagnostic':return self.jobs.start(self.workspace,'diagnostic',diagnostic=args['python'])
        if name=='run_scenario':return self.jobs.start(self.workspace,'diagnostic',diagnostic=scenario_script(args['scenario_json']))
        raise ValueError('unknown tool')

    def handle(self,method,params,primary_thread):
        if method=='item/permissions/requestApproval':return {'permissions':{},'scope':'turn'}
        if method=='item/tool/requestUserInput':return {'answers':{}}
        if method!='item/tool/call':return {'decision':'decline'}
        try:
            if not primary_thread or params.get('threadId')!=primary_thread:
                raise ValueError('only the primary task thread may use project tools')
            name=params.get('tool');args=params.get('arguments')
            if name not in self.schemas:raise ValueError('unknown tool')
            validate_arguments(args,self.schemas[name])
            call_id=params.get('callId')
            if not isinstance(call_id,str) or not call_id:raise ValueError('missing tool call identity')
            value=self.dispatch(name,args,digest({'thread':primary_thread,'call':call_id}))
            success=True
        except (ValueError,KeyError,OSError,TypeError) as exc:
            value={'error':str(exc)[:500]};success=False
        return {'contentItems':[{'type':'inputText','text':json.dumps(value,ensure_ascii=False)}],'success':success}
