"""Bounded local execution with an OS sandbox, not just a temporary cwd.

This is an educational judge, not a multi-tenant hostile-code service. The
runtime cannot read the course/learner home, write outside its scratch directory,
or use the network. Compilation is also bounded and isolated on macOS.
"""
from __future__ import annotations
from dataclasses import dataclass
import importlib
import json
import math
import os
from pathlib import Path
import platform
import resource
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time

OUTPUT_LIMIT=1_048_576

@dataclass
class Result:
    verdict: str
    seconds: float=0
    output: str=''
    detail: str=''
    memory_kb: int=0

class JudgeError(RuntimeError): pass

def _bounds(cpu, memory_mb):
    def apply():
        resource.setrlimit(resource.RLIMIT_CPU,(max(1,math.ceil(cpu)),max(2,math.ceil(cpu)+1)))
        resource.setrlimit(resource.RLIMIT_FSIZE,(OUTPUT_LIMIT,OUTPUT_LIMIT))
        resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
        if platform.system()=='Linux':
            resource.setrlimit(resource.RLIMIT_AS,(memory_mb*1024*1024,memory_mb*1024*1024))
        os.umask(0o077)
    return apply

def sandbox_command(command, scratch):
    scratch=Path(scratch).resolve()
    system=platform.system()
    if system=='Darwin':
        sandbox=shutil.which('sandbox-exec')
        if not sandbox: raise JudgeError('macOS sandbox-exec is unavailable; the judge refuses unsandboxed execution.')
        # Paths are encoded as Scheme strings, with quotes/backslashes escaped.
        roots=['/usr','/System','/Library','/opt/homebrew','/Applications',
               '/private/var/db/dyld','/private/var/select','/private/etc',
               '/dev',str(Path(sys.base_prefix).resolve()),str(scratch)]
        reads='(literal "/") '+' '.join('(subpath '+json.dumps(x)+')' for x in roots)
        profile='(version 1)(deny default)(allow process*)(allow sysctl-read)(allow mach-lookup)(allow ipc-posix-shm)(allow file-read-metadata)(allow file-read* '+reads+')(allow file-map-executable '+reads+')(allow file-write* (subpath '+json.dumps(str(scratch))+'))(allow file-write* (literal "/dev/null"))'
        return [sandbox,'-p',profile,*command]
    if system=='Linux':
        bwrap=shutil.which('bwrap')
        if not bwrap: raise JudgeError('Linux needs bubblewrap: install bubblewrap, then rerun. Unsandboxed execution is disabled.')
        cmd=[bwrap,'--die-with-parent','--unshare-all','--new-session','--proc','/proc','--dev','/dev','--tmpfs','/tmp']
        for p in ['/usr','/lib','/lib64','/bin','/etc/ld.so.cache',str(Path(sys.base_prefix).resolve())]:
            if Path(p).exists(): cmd+=['--ro-bind',p,p]
        cmd+=['--bind',str(scratch),str(scratch),'--chdir',str(scratch),'--',*command]
        return cmd
    raise JudgeError('Supported judge platforms: macOS and Linux with bubblewrap.')

def _environment(scratch):
    return {'PATH':'/usr/bin:/bin:/opt/homebrew/bin','HOME':str(scratch),
            'TMPDIR':str(scratch),'PYTHONDONTWRITEBYTECODE':'1','LANG':'C','LC_ALL':'C'}

def _kill(proc):
    try: os.killpg(proc.pid,signal.SIGKILL)
    except ProcessLookupError: pass
    proc.wait()

def run_bounded(command, text, scratch, seconds=2.0,memory_mb=256):
    """Execute one process tree; cap wall time and both output streams."""
    scratch=Path(scratch)
    out=scratch/'stdout.txt'; err=scratch/'stderr.txt'
    wrapped=sandbox_command(command,scratch)
    # time's per-child peak RSS is reliable even when several submissions run.
    if platform.system()=='Darwin': wrapped=['/usr/bin/time','-l',*wrapped]
    else: wrapped=['/usr/bin/time','-f','__RSS_KB__:%M',*wrapped] if Path('/usr/bin/time').exists() else wrapped
    start=time.monotonic()
    with out.open('wb') as stdout,err.open('wb') as stderr:
        proc=subprocess.Popen(wrapped,stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,
                              cwd=scratch,env=_environment(scratch),start_new_session=True,
                              preexec_fn=_bounds(seconds,memory_mb))
        try: proc.communicate(text.encode(),timeout=seconds+0.25)
        except subprocess.TimeoutExpired:
            _kill(proc)
            return Result('TLE',time.monotonic()-start,detail='Wall-clock limit exceeded')
    elapsed=time.monotonic()-start
    output=out.read_text(errors='replace')[:OUTPUT_LIMIT]
    diagnostic=err.read_text(errors='replace')[:OUTPUT_LIMIT]
    memory=0
    for line in diagnostic.splitlines():
        if 'maximum resident set size' in line:
            try: memory=int(line.split()[0])//1024
            except ValueError: pass
        if line.startswith('__RSS_KB__:'):
            try: memory=int(line.split(':')[1])
            except ValueError: pass
    if 'sandbox_apply' in diagnostic or 'bwrap:' in diagnostic:
        return Result('SANDBOX',elapsed,detail='OS sandbox unavailable in this host context. Run see from a normal local terminal. '+diagnostic[:300])
    if out.stat().st_size>=OUTPUT_LIMIT or err.stat().st_size>=OUTPUT_LIMIT:
        return Result('OLE',elapsed,detail='Output exceeded 1 MiB',memory_kb=memory)
    if memory>memory_mb*1024:
        return Result('MLE',elapsed,detail=f'Peak RSS {memory//1024} MiB exceeds {memory_mb} MiB',memory_kb=memory)
    if proc.returncode:
        code=-proc.returncode
        verdict='TLE' if code in {signal.SIGXCPU,signal.SIGKILL} else 'RE'
        return Result(verdict,elapsed,output,f'Exit status {proc.returncode}. '+diagnostic[:2000],memory)
    return Result('OK',elapsed,output,'',memory)

class Executable:
    def __init__(self, source, seconds=2.0,memory_mb=256):
        self.source=Path(source).resolve()
        if not self.source.is_file(): raise JudgeError(f'Solution file missing: {source}')
        self.temp=tempfile.TemporaryDirectory(prefix='seeing-judge-')
        self.scratch=Path(self.temp.name)
        self.seconds=seconds;self.memory_mb=memory_mb
        destination=self.scratch/('main'+self.source.suffix)
        shutil.copyfile(self.source,destination)
        if self.source.suffix=='.py':
            self.command=[str(Path(sys.executable).resolve()),'-I','-B',str(destination)]
        elif self.source.suffix in {'.cpp','.cc','.cxx'}:
            compiler=shutil.which('clang++') or shutil.which('g++')
            if not compiler: raise JudgeError('A C++20 compiler is required (clang++ or g++).')
            binary=self.scratch/'solution'
            # <bits/stdc++.h> is a GCC header; Apple clang has none. Offer a stand-in that is searched
            # only after the system directories, so a real one still wins where it exists.
            shim=Path(__file__).resolve().parent.parent/'templates/include/bits/stdc++.h'
            extra=[]
            if shim.is_file():
                (self.scratch/'fallback/bits').mkdir(parents=True);shutil.copyfile(shim,self.scratch/'fallback/bits/stdc++.h')
                extra=['-idirafter',str(self.scratch/'fallback')]
            compile_result=run_bounded([compiler,'-std=c++20','-O2','-pipe',*extra,str(destination),'-o',str(binary)],'',self.scratch,30,2048)
            if compile_result.verdict!='OK':
                self.close()
                raise JudgeError('Compilation failed: '+compile_result.verdict+' '+compile_result.detail)
            self.command=[str(binary)]
        else:
            self.close(); raise JudgeError('Use a .cpp or .py solution file.')

    def run(self,text):
        return run_bounded(self.command,text,self.scratch,self.seconds,self.memory_mb)

    def close(self):
        self.temp.cleanup()

    def __enter__(self): return self
    def __exit__(self,*args): self.close()

def same_output(a,b):
    return a.split()==b.split()
