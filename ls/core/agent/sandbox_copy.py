"""Sealed, standard-library-only bootstrap for disposable tmpfs workspaces."""
from __future__ import annotations

import os
from pathlib import Path
import stat
import sys


def copy_inputs(source: Path, target: Path):
    count,total=0,0
    def fail(error):
        raise error
    for directory,names,files in os.walk(source,followlinks=False,onerror=fail):
        destination=target/Path(directory).relative_to(source)
        for name in (*names,*files):
            count+=1
            if count>30000:
                raise ValueError('Sandbox input inventory exceeds limit')
            entry=Path(directory)/name
            info=entry.lstat()
            if stat.S_ISDIR(info.st_mode):
                (destination/name).mkdir(mode=0o700)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink==1:
                fd=os.open(entry,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
                with os.fdopen(fd,'rb') as reader:
                    actual=os.fstat(reader.fileno())
                    if (actual.st_dev,actual.st_ino)!=(info.st_dev,info.st_ino):
                        raise ValueError('Sandbox input changed during projection')
                    with (destination/name).open('xb') as writer:
                        while data:=reader.read(1024*1024):
                            total+=len(data)
                            if total>256*1024*1024:
                                raise ValueError('Sandbox inputs exceed byte limit')
                            writer.write(data)
                        os.fchmod(writer.fileno(),0o600|(actual.st_mode&0o100))
            else:
                raise ValueError('Sandbox input requires regular files and directories')


def main():
    if not sys.flags.isolated or not sys.dont_write_bytecode or len(sys.argv)<2:
        raise RuntimeError('Sandbox bootstrap requires isolated execution and command')
    command=sys.argv[1:]
    if Path(command[0]).parent!=Path('/usr/bin') or str(Path(command[0]))!=command[0]:
        raise ValueError('Sandbox command requires an explicit system executable')
    os.umask(0o077)
    copy_inputs(Path('/inputs'),Path('/work'))
    os.chdir('/work')
    os.execv(command[0],command)


if __name__=='__main__':
    main()
