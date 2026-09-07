"""Explicit ordered refresh of nested repository instruction snapshots."""
from .broker_rpc import _encode
from .file_grants import relative


def candidates(directory):
    parts=() if directory=='.' else relative(directory)
    if len(parts)>15:
        raise ValueError('Context refresh exceeds 16 instruction levels')
    return ['/'.join((*parts[:index],'AGENTS.md')) for index in range(len(parts)+1)]


def refresh(owner,broker,directory):
    paths=candidates(directory)
    def check():
        for path in paths:
            broker.grant.check(broker.grant.task,broker.grant.session,'read',path,provider=True)
        owner._check()
    check();resources=[];missing=[];total=0
    for path in paths:
        try:
            value=owner.read_text(broker,path,for_provider=True)
        except FileNotFoundError:
            missing.append(path)
            continue
        size=len(value['content'].encode());total+=size
        if size>16*1024 or total>64*1024:
            raise ValueError('Nested context exceeds content bounds')
        resources.append(dict(path=path,**value))
    result={'directory':directory,'resources':resources,'missing':missing}
    if len(_encode(result))>256*1024:
        raise ValueError('Nested context exceeds encoded result limit')
    check()
    return result
