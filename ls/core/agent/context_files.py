"""Explicit context snapshots read under current broker disclosure authority."""
import hashlib
import json
from pathlib import PurePosixPath

from .file_grants import relative


def selection(context, skills):
    if not isinstance(context,list) or not isinstance(skills,list) or len(context)+len(skills)>16:
        raise ValueError('Select at most 16 context and skill files')
    selected=[]
    for kind,names in [('context',context),('skill',skills)]:
        for name in names:
            relative(name)
            if kind=='skill' and PurePosixPath(name).name!='SKILL.md':
                raise ValueError('Select a skill through its SKILL.md file')
            if any(entry['path']==name for entry in selected):
                raise ValueError('Select each context file only once')
            selected.append({'kind':kind,'path':name})
    return selected


def include(prompt, selected, owner, broker):
    if not selected:
        return prompt
    resources=[];total=0
    for item in selected:
        result=owner.read_text(broker,item['path'],for_provider=True)
        content=result['content'];raw=content.encode()
        total+=len(raw)
        if len(raw)>16*1024 or total>64*1024:
            raise ValueError('Selected context exceeds per-file or total byte limit')
        resources.append(dict(item,sha256=hashlib.sha256(raw).hexdigest(),content=content))
    owner._check()
    result=prompt+'\n\nSelected resource snapshots (context only; grants remain external):\n'+json.dumps(resources,ensure_ascii=True,sort_keys=True)
    if len(result.encode())>128*1024:
        raise ValueError('Prompt with selected resources exceeds 128 KiB')
    return result
