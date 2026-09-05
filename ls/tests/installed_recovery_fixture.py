"""Explicit installed-runtime crash qualification; run only with a qualified delegation.

Invoke with installed Python -I -B, this file, RUNTIME_ROOT, CGROUP_PARENT.
The fixture creates private temporary projects and only calls its loopback provider.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ls.core.agent.coding_run import CodingGrant, RunPaths, disclosure_digest, run_coding
from ls.core.agent.coding_protocol import profile_digest
from ls.core.agent.file_grants import FileGrant
from ls.core.agent.process_rpc import Recipe
from ls.core.agent.recovery import recover_checkpoint
from ls.core.agent.resource_group import Limits
from ls.core.agent.session_owner import lease
from ls.core.branding import user_agent


def configuration(base, runtimes, parent, port):
    profile = {'base_url':f'http://127.0.0.1:{port}/v1/', 'api':'chat_completions', 'model':'fixture',
               'credential_env':'FIXTURE_KEY','timeout_seconds':10,'capabilities':['tools','streaming'],'allow_loopback_http':True}
    payload = {'schema_version':1,'run_id':'run','profile':profile,'credential':'fixture-not-a-secret',
        'prompt':'Read, edit and test the fixture.','instructions':'Use only granted tools.','history':None,
        'request_limit':8,'tool_limit':16,'token_limit':32768}
    paths = RunPaths(runtimes,base/'sessions',base/'leases',base/'snapshots',base/'scratch',parent)
    files = FileGrant('task','session',base/'workspace',('src',),('src',),('src',),time.monotonic()+30)
    recipes = {'test':Recipe(('/usr/bin/python3','-I','-B','-c',
        "from pathlib import Path;assert Path('src/a.txt').read_text()=='changed';print('fixture passed')"),('src/a.txt',),5)}
    return payload, paths, files, recipes


def crash_child(base, runtimes, parent, port, window):
    from ls.core.agent import supervisor, tool_results, process_broker
    payload, paths, files, recipes = configuration(base,runtimes,parent,port)
    worker = None
    popen = supervisor.subprocess.Popen
    def spawn(command, *args, **kwargs):
        nonlocal worker
        process = popen(command,*args,**kwargs)
        if 'ls.core.agent.coding_worker' in command:
            worker = process.pid
        return process
    supervisor.subprocess.Popen = spawn
    def crash():
        (base/'crash.json').write_text(json.dumps({'worker':worker,'window':window}))
        os._exit(73)
    save = tool_results.save
    def receipt(owner,result,**kwargs):
        if 'output' in result and window == 'before-receipt':
            crash()
        digest = save(owner,result,**kwargs)
        if 'output' in result and window == 'after-receipt':
            crash()
        return digest
    tool_results.save = receipt
    run = process_broker.run
    def process(*args,**kwargs):
        result = run(*args,**kwargs)
        if window == 'before-outcome':
            crash()
        return result
    process_broker.run = process
    authority = CodingGrant('task','session',disclosure_digest(payload),files.expires)
    run_coding(paths,payload,authority,files,recipes,limits=Limits(tasks=16),on_event=lambda event:None)
    raise AssertionError('Crash injection was not reached')


def qualify(runtimes, parent):
    captured = []
    class Provider(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            captured.append(self.headers['User-Agent'])
            turn = len(captured)
            if turn == 1:
                name,args,call = 'read_file',{'path':'src/a.txt'},'read'
            elif turn == 2:
                result = json.loads([m for m in body['messages'] if m['role']=='tool'][-1]['content'])
                assert result['content']=='original'
                name,args,call = 'write_file',{'path':'src/a.txt','content':'changed','expected_before':result['sha256']},'write'
            elif turn == 3:
                name,args,call = 'run_command',{'name':'test'},'test'
            else:
                assert turn == 4, 'Unexpected repeated model request'
                result = json.loads([m for m in body['messages'] if m['role']=='tool'][-1]['content'])
                assert result['status']=='completed' and result['output']['stdout']=='fixture passed\n'
            delta = {'content':'recovered without replay'} if turn==4 else {'tool_calls':[
                {'index':0,'id':call,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}
            chunks = [{'id':f'completion-{turn}','object':'chat.completion.chunk','created':1,'model':'fixture',
                'choices':[{'index':0,'delta':piece,'finish_reason':finish}]} for piece,finish in
                ((delta,None),({},'stop' if turn==4 else 'tool_calls'))]
            raw = (''.join('data: '+json.dumps(x)+'\n\n' for x in chunks)+'data: [DONE]\n\n').encode()
            self.send_response(200);self.send_header('Content-Type','text/event-stream')
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    http = ThreadingHTTPServer(('127.0.0.1',0),Provider)
    thread = threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    reports = []
    try:
        for window in ('after-receipt','before-receipt','before-outcome'):
            captured.clear()
            base = Path(tempfile.mkdtemp(prefix='coding-recovery-'))
            for name in ('workspace','sessions','leases','snapshots','scratch'):
                (base/name).mkdir(mode=0o700)
            (base/'workspace/src').mkdir();(base/'workspace/src/a.txt').write_text('original')
            child = subprocess.run([sys.executable,'-I','-B',str(Path(__file__).resolve()),'--crash',str(base),
                str(runtimes),str(parent),str(http.server_port),window],capture_output=True,text=True,timeout=40)
            assert child.returncode==73,child.stderr
            marker = json.loads((base/'crash.json').read_text());assert isinstance(marker['worker'],int)
            deadline = time.monotonic()+3
            while True:
                status = Path(f"/proc/{marker['worker']}/stat")
                if not status.exists() or status.read_text().split(') ',1)[1].split()[0]=='Z':
                    break
                assert time.monotonic()<deadline,'Orphan SDK worker retained execution'
                time.sleep(0.02)
            assert len(captured)==3 and all(x==user_agent() for x in captured)
            payload, paths, files, recipes = configuration(base,runtimes,parent,http.server_port)
            with lease(paths.sessions,task='task',session='session',workspace=files.root,expires=files.expires) as owner:
                operations = owner.inspect();assert len(operations)==2
                process = next(v for v in operations.values() if v['intent']['kind']=='process')
                checkpoint = process['intent']['checkpoint']
                before = owner._journal.frontier()
                original = owner._checkpoints().load(checkpoint)
                if window == 'after-receipt':
                    recovered = recover_checkpoint(owner,runtimes,checkpoint,profile=profile_digest(payload['profile']),recipes=recipes)
                    history = owner.resume_checkpoint(recovered,profile=profile_digest(payload['profile']))
                    assert b'fixture passed' in history
                else:
                    expected = FileNotFoundError if window=='before-receipt' else PermissionError
                    try:recover_checkpoint(owner,runtimes,checkpoint,profile=profile_digest(payload['profile']),recipes=recipes)
                    except expected:pass
                    else:raise AssertionError('Missing or uncertain evidence was accepted')
                assert owner._journal.frontier()==before and owner._checkpoints().load(checkpoint)==original
            if window == 'after-receipt':
                resumed = payload|{'run_id':'continued','history':history.decode(),'prompt':'Continue from recovered results.'}
                authority = CodingGrant('task','session',disclosure_digest(resumed),files.expires)
                outcome = run_coding(paths,resumed,authority,files,recipes,limits=Limits(tasks=16),on_event=lambda event:None,resume=recovered)
                assert outcome.status=='completed' and outcome.data['output']=='recovered without replay',outcome
                with lease(paths.sessions,task='task',session='session',workspace=files.root,expires=files.expires) as owner:
                    assert owner.inspect()==operations
            if window == 'before-outcome':
                authority = CodingGrant('task','session',disclosure_digest(payload),files.expires)
                try:run_coding(paths,payload,authority,files,recipes,limits=Limits(tasks=16),on_event=lambda event:None)
                except PermissionError as error:
                    assert 'reconciliation' in str(error)
                else:raise AssertionError('Uncertain session dispatched new work')
                with lease(paths.sessions,task='task',session='session',workspace=files.root,expires=files.expires) as owner:
                    assert owner.inspect()==operations
            assert len(captured)==(4 if window=='after-receipt' else 3)
            assert all(x==user_agent() for x in captured)
            assert (base/'workspace/src/a.txt').read_text()=='changed'
            revoked = threading.Event();revoked.set()
            try:
                with lease(paths.sessions,task='task',session='session',workspace=files.root,expires=files.expires,revoked=revoked):
                    raise AssertionError('Revoked recovery owner acquired')
            except PermissionError:pass
            reports.append({'window':window,'requests':len(captured),'operations':2,'worker_stopped':True,
                            'continued':window=='after-receipt','fixture':str(base)})
    finally:
        http.shutdown();http.server_close();thread.join()
    print(json.dumps({'cases':reports,'user_agent':user_agent()}))


if __name__ == '__main__':
    os.umask(0o077)
    if not sys.flags.isolated or not sys.dont_write_bytecode:
        raise RuntimeError('Use installed isolated Python for this explicit qualification')
    if sys.argv[1]=='--crash':
        crash_child(Path(sys.argv[2]),Path(sys.argv[3]),Path(sys.argv[4]),int(sys.argv[5]),sys.argv[6])
    else:
        qualify(Path(sys.argv[1]),Path(sys.argv[2]))
