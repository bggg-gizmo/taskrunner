"""Expand saved, reusable workflow modules without executing nested jobs.

Every expansion is validated before an effectful action runs; module cycles,
excessive nesting, and enormous expanded sequences are rejected in advance.
"""
from __future__ import annotations
import copy
from .flow import validate_workflow

MAX_DEPTH=8
MAX_EXPANDED_STEPS=100000


def expand_modules(store, steps, ancestors=()):
    roots=tuple(int(x) for x in ancestors)
    total=[0]
    def walk(source, chain):
        if len(chain)>MAX_DEPTH:
            raise ValueError('Reusable task module nesting exceeds 8 levels')
        validate_workflow(source)
        result=[]
        for step in source:
            if step['type']!='run_module':
                result.append(copy.deepcopy(step))
                total[0]+=1
            else:
                if step.get('verify',{}).get('kind','none')!='none' or step.get('retry_count',0):
                    raise ValueError('Reusable module-level retries or verification cannot be safely expanded; add them to its child actions')
                job_id=int(step['params']['task_id'])
                if job_id in chain:
                    raise ValueError('Recursive task module reference detected: '+ ' -> '.join(map(str,chain+(job_id,))))
                job=store.get_job(job_id)
                if job is None:
                    raise LookupError(f'Reusable task module not found: task #{job_id}')
                children=walk(job['actions'],chain+(job_id,))
                # Preserve the module action's timing semantics around its expanded steps.
                if children:
                    children[0]['delay_before']=round(float(children[0].get('delay_before',0))+float(step.get('delay_before',0)),3)
                    children[-1]['delay_after']=round(float(children[-1].get('delay_after',0))+float(step.get('delay_after',0)),3)
                result.extend(children)
            if total[0]>MAX_EXPANDED_STEPS:
                raise ValueError(f'Expanded workflow exceeds {MAX_EXPANDED_STEPS} actions')
        return result
    output=walk(steps,roots)
    validate_workflow(output)
    return output
