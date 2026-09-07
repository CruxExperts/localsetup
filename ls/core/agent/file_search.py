"""Bounded literal text search over explicitly disclosed regular files."""
from .broker_rpc import _encode
from .file_grants import relative


def search(owner, broker, data):
    if not isinstance(data,dict) or set(data)!={'paths','text'}:
        raise ValueError('Invalid search schema')
    paths,text=data['paths'],data['text']
    if (not isinstance(paths,list) or not 1<=len(paths)<=32 or any(not isinstance(p,str) for p in paths)
            or len(set(paths))!=len(paths) or not isinstance(text,str) or not text or len(text.encode())>1024
            or '\n' in text or '\r' in text):
        raise ValueError('Search requires distinct paths and bounded single-line literal text')
    for path in paths:
        relative(path)
        broker.grant.check(broker.grant.task,broker.grant.session,'read',path,provider=True)
    files=[];contents=[];total=0
    for path in paths:
        value=owner.read_text(broker,path,for_provider=True)
        total+=len(value['content'].encode())
        if total>4*1024*1024:
            raise ValueError('Search input exceeds 4 MiB')
        files.append({'path':path,'sha256':value['sha256']})
        contents.append((path,value['content']))
    result={'files':files,'matches':[],'truncated':False}
    if len(_encode(result))>256*1024-1024:
        raise ValueError('Search metadata exceeds output limit')
    def finish():
        for path in paths:
            broker.grant.check(broker.grant.task,broker.grant.session,'read',path,provider=True)
        owner._check()
        return result
    for path,content in contents:
        for number,line in enumerate(content.splitlines(),1):
            owner._check()
            if text not in line:
                continue
            match={'path':path,'line':number,'text':line[:512],'text_truncated':len(line)>512}
            if len(result['matches'])>=100 or len(_encode(result))+len(_encode(match))>256*1024-1024:
                result['truncated']=True
                return finish()
            result['matches'].append(match)
    return finish()
