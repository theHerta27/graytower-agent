"""Runtime dynamic tools. The host owns paths, edits and physical execution."""
import json
import re
from .workspace import digest
from .sandbox import CHECK_SETS


def tool(name, description, properties, required=()):
    return {'type':'function','name':name, 'description':description, 'inputSchema':{
        'type':'object','properties':properties,'required':list(required),'additionalProperties':False}}


TEXT={'type':'string','minLength':1,'maxLength':250}
TOOL_SPECS=[
    tool('project_status','查看当前项目版本、候选文件、真实Diff与已有检查。范围校验不等于测试通过。',{}),
    tool('read_file','只读候选内源码或规则。返回完整文件身份，可按行分段读取。',
         {'path':TEXT,'start_line':{'type':'integer','minimum':1},'max_lines':{'type':'integer','minimum':1,'maximum':400}},['path']),
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
    def __init__(self,workspace,jobs):
        self.workspace=workspace;self.jobs=jobs

    def dispatch(self,name,args,operation):
        if name=='project_status':
            view=self.workspace.inspect()
            if len(view['patch'])>24000:
                view['patch']=view['patch'][:24000];view['patch_truncated']=True
            return {**view,'checks':self.jobs.list(self.workspace)}
        if name=='read_file':
            value=self.workspace.read_file(args['path'])
            lines=value.pop('text').splitlines(keepends=True)
            start=args.get('start_line',1);count=args.get('max_lines',200)
            selected=''.join(lines[start-1:start-1+count])
            return {**value,'text':selected[:24000],'start_line':start,'total_lines':len(lines),
                    'truncated':start>1 or start-1+count<len(lines) or len(selected)>24000}
        if name=='search_code':return self.workspace.search(args['query'])
        if name=='write_file':return self.workspace.write_file(operation,**args)
        if name=='replace_text':return self.workspace.replace_text(operation,**args)
        if name=='start_check':return self.jobs.start(self.workspace,args['check_set'])
        if name=='read_check':return self.jobs.read(args['job_id'],self.workspace)
        if name=='start_diagnostic':return self.jobs.start(self.workspace,'diagnostic',diagnostic=args['python'])
        raise ValueError('unknown tool')

    def handle(self,method,params,primary_thread):
        if method=='item/permissions/requestApproval':return {'permissions':{},'scope':'turn'}
        if method=='item/tool/requestUserInput':return {'answers':{}}
        if method!='item/tool/call':return {'decision':'decline'}
        try:
            if not primary_thread or params.get('threadId')!=primary_thread:
                raise ValueError('only the primary task thread may use project tools')
            name=params.get('tool');args=params.get('arguments')
            if name not in SCHEMAS:raise ValueError('unknown tool')
            validate_arguments(args,SCHEMAS[name])
            call_id=params.get('callId')
            if not isinstance(call_id,str) or not call_id:raise ValueError('missing tool call identity')
            value=self.dispatch(name,args,digest({'thread':primary_thread,'call':call_id}))
            success=True
        except (ValueError,KeyError,OSError,TypeError) as exc:
            value={'error':str(exc)[:500]};success=False
        return {'contentItems':[{'type':'inputText','text':json.dumps(value,ensure_ascii=False)}],'success':success}
