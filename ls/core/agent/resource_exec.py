"""Trusted isolated pre-exec cgroup membership trampoline, never a model tool."""
from __future__ import annotations

import os
import sys


def main():
    if not sys.flags.isolated or not sys.dont_write_bytecode:
        raise RuntimeError('Resource launcher requires isolated execution')
    if len(sys.argv)<4 or sys.argv[2]!='--':
        raise ValueError('Resource launcher requires membership descriptor and command')
    fd=int(sys.argv[1])
    if fd<3 or not os.path.isabs(sys.argv[3]):
        raise ValueError('Invalid resource launcher descriptor or executable')
    try:
        value=str(os.getpid()).encode('ascii')
        if os.write(fd,value)!=len(value):
            raise OSError('Incomplete resource membership write')
    finally:
        os.close(fd)
    os.execv(sys.argv[3],sys.argv[3:])


if __name__=='__main__':
    main()
