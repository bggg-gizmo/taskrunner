"""Regenerate the portable Task Runner job export JSON Schema from the action catalog."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from task_runner.actions import ACTIONS


def generate() -> dict:
    action_types=[]
    for key, action in ACTIONS.items():
        properties={}
        required=[]
        for field in action.fields:
            type_name={'text':'string','multiline':'string','path':'string','choice':'string',
                       'int':'integer','float':'number','bool':'boolean'}[field.kind]
            item={'type':type_name,'title':field.label,'default':field.default}
            if field.options:item['enum']=list(field.options)
            properties[field.key]=item
            if field.required:required.append(field.key)
        action_types.append({
            'type':'object',
            'required':['type','params'],
            'properties':{
                'type':{'const':key},
                'params':{'type':'object','properties':properties,'required':required,'additionalProperties':True},
                'verify':{'$ref':'#/$defs/verification'},
                'retry_count':{'type':'integer','minimum':0,'maximum':100},
                'retry_delay':{'type':'number','minimum':0,'maximum':3600},
                'delay_before':{'type':'number','minimum':0,'maximum':3600},
                'delay_after':{'type':'number','minimum':0,'maximum':3600},
            },'additionalProperties':True
        })
    return {
        '$schema':'https://json-schema.org/draft/2020-12/schema',
        '$id':'taskrunner-job.schema.json',
        'title':'Task Runner portable job export',
        'description':'JSON created by Task Runner Export JSON. Imported jobs are disabled until reviewed.',
        'type':'object',
        'required':['format','version','job'],
        'properties':{
            'format':{'const':'TaskRunnerJob'},
            'version':{'const':1},
            'job':{'type':'object','required':['name','description','enabled','schedule_kind','schedule','actions'],
                   'properties':{
                       'name':{'type':'string','minLength':1},
                       'description':{'type':'string'},
                       'enabled':{'oneOf':[{'type':'boolean'},{'type':'integer','enum':[0,1]}]},
                       'schedule_kind':{'enum':['manual','once','interval','daily','weekly','cron']},
                       'schedule':{'type':'object'},
                       'actions':{'type':'array','minItems':1,'items':{'oneOf':action_types}}
                   },'additionalProperties':True}
        },'additionalProperties':False,
        '$defs':{'verification':{
            'type':'object','properties':{
                'kind':{'enum':['none','file_exists','window_exists','window_missing','file_missing','clipboard_contains',
                                'browser_visible','browser_hidden','image_visible','screen_changed']},
                'target':{'type':'string'},
                'timeout':{'type':'number','minimum':0,'maximum':3600}
            },'additionalProperties':True}}
    }


def main() -> int:
    target=ROOT/'schemas'/'taskrunner-job.schema.json'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(generate(),indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print('Updated',target)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
