import os
import pty
import threading
import time

import pytest

from ls.core.agent.interactive import Terminal
from ls.core.agent.steering import Steering
from ls.core.agent.approvals import Approvals


def setup():
    master,slave=pty.openpty();cancelled=threading.Event()
    ui=Terminal(time.monotonic()+3,cancelled,input_fd=slave,output_fd=slave)
    ui.steering=Steering(cancelled,ui.expires);ui.steering.bind('task','session','profile')
    ui.approvals=Approvals();ui.approvals.bind('task','session','profile')
    return master,slave,ui,cancelled


def test_multiline_steering_and_cancel_with_real_terminal():
    master,slave,ui,cancelled=setup()
    try:
        os.write(master,b'first line\nsecond line\n/send\n')
        assert ui.prompt()=='first line\nsecond line'
        os.write(master,b'/steer new direction\n')
        deadline=time.monotonic()+1
        while not ui.steering.pending and time.monotonic()<deadline:time.sleep(.01)
        assert ui.steering.take()==['new direction']
        os.write(master,b'/cancel\n');assert cancelled.wait(1)
    finally:ui.close();os.close(master);os.close(slave)


def test_approval_uses_exact_displayed_challenge():
    master,slave,ui,cancelled=setup()
    try:
        os.write(master,b'task\n/send\n');ui.prompt()
        def emit(packet):
            ui.approval(packet)
            os.write(master,('/approve '+packet['challenge']+'\n').encode())
        assert ui.approvals.require('file.read',{'path':'x'},{},emit,ui.check)=={'path':'x'}
        assert not cancelled.is_set()
    finally:ui.close();os.close(master);os.close(slave)


def test_nonterminal_refused_and_shutdown_bounded():
    read,write=os.pipe()
    try:
        with pytest.raises(ValueError):Terminal(time.monotonic()+1,threading.Event(),input_fd=read,output_fd=write)
    finally:os.close(read);os.close(write)
    master,slave,ui,cancelled=setup()
    try:
        os.write(master,b'task\n/send\n');ui.prompt()
        start=time.monotonic();ui.close();assert time.monotonic()-start<.5 and not cancelled.is_set()
    finally:os.close(master);os.close(slave)


def test_finish_joins_blocked_writer_and_restores_fd_before_final_output():
    from ls.core.agent.run_cli import finish_input
    master,slave,ui,cancelled=setup();stopped=[]
    try:
        os.set_blocking(slave,False)
        while True:
            try:os.write(slave,b'x'*4096)
            except BlockingIOError:break
        os.set_blocking(slave,True)
        entered=threading.Event()
        def writer():
            entered.set()
            try:ui.write('acknowledgement'*1000)
            except InterruptedError:stopped.append(True)
        ui.thread=threading.Thread(target=writer);ui.thread.start();assert entered.wait(1)
        deadline=time.monotonic()+1
        while os.get_blocking(slave) and time.monotonic()<deadline:time.sleep(.005)
        assert not os.get_blocking(slave)
        finish_input(ui)
        assert not ui.thread.is_alive() and stopped and os.get_blocking(slave)
    finally:ui.close();os.close(master);os.close(slave)
