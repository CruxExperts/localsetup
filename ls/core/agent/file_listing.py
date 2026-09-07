"""Anchored, bounded metadata discovery under current disclosure authority."""
import os
import stat
import time

from .broker_rpc import _encode
from .file_broker import parent
from .runtime_lock import runtime_use


MAX_RESULT = 256*1024

def listing(owner, broker, path):
    with owner._operation():
        bound=owner._broker(broker);grant=bound.grant
        def check():
            parts=grant.check(grant.task,grant.session,'list',path,provider=True)
            owner._check()
            return parts
        parts=check();entries=[];truncated=False
        if len(_encode({'path':path,'entries':[],'truncated':False}))>MAX_RESULT:
            raise ValueError('Listing metadata exceeds output limit')
        with runtime_use(bound.lease_root,exclusive=False,timeout=max(0,grant.expires-time.monotonic())):
            # The synthetic leaf is never read or created; its parent is the selected directory.
            with parent(grant.root,(*parts,'_directory_listing_')) as (directory,_):
                before=os.fstat(directory)
                with os.scandir(directory) as iterator:
                    for count,entry in enumerate(iterator):
                        check()
                        if count>=4096:
                            truncated=True;break
                        name='/'.join((*parts,entry.name))
                        try:
                            name.encode('utf-8')
                            grant.check(grant.task,grant.session,'read',name,provider=True)
                        except (PermissionError,UnicodeError):
                            continue
                        info=entry.stat(follow_symlinks=False)
                        if info.st_uid!=os.getuid() or info.st_mode&0o7000:
                            continue
                        if stat.S_ISREG(info.st_mode) and info.st_nlink==1:
                            kind='file'
                        elif stat.S_ISDIR(info.st_mode):
                            kind='directory'
                        else:
                            continue
                        value={'path':name,'kind':kind}
                        entries.append(value)
                        if len(_encode({'path':path,'entries':entries,'truncated':False}))>MAX_RESULT:
                            entries.pop();truncated=True;break
                after=os.fstat(directory)
                if (before.st_mtime_ns,before.st_ctime_ns)!=(after.st_mtime_ns,after.st_ctime_ns):
                    raise PermissionError('Directory changed while listing')
        result={'path':path,'entries':sorted(entries,key=lambda value:value['path']),'truncated':truncated}
        for entry in result['entries']:
            grant.check(grant.task,grant.session,'read',entry['path'],provider=True)
        check()
        return result
