"""Bounded 1920x1080 ReSTIR PT GPU/memory preflight; no production accumulation.

Delegates to the frozen six-view smoke pipeline after locally restricting its
budget override to at most two 1-spp frames. Existing source and reference
runtimes are never changed. Memory samples are global GPU usage, including
other apps, and polling can miss short-lived peaks.
"""
from contextlib import contextmanager
from pathlib import Path
import argparse
import json
import os
import subprocess
import threading
import time

from . import cgns_pt_smoke as smoke
from . import cgns_pt_six_view_smoke as six


def validate_preflight(width, height, frames):
    if (type(width),type(height),type(frames)) != (int,int,int) or (width,height)!=(1920,1080) or not 1<=frames<=2:
        raise ValueError('Full HD resource preflight requires 1920x1080 and one or two frames')


@contextmanager
def fullhd_budget_override():
    original=smoke.validate_budget
    smoke.validate_budget=validate_preflight
    try:
        yield
    finally:
        smoke.validate_budget=original


def parse_gpu_stats(text):
    rows=[x for x in text.splitlines() if x.strip()]
    if len(rows)!=1: raise ValueError('Expected exactly one GPU')
    cols=rows[0].split(',')
    if len(cols)!=4:raise ValueError('Malformed nvidia-smi output')
    try: index,total,used,util=(int(x.strip()) for x in cols)
    except ValueError as exc:raise ValueError('Non-numeric GPU stats') from exc
    if index<0 or total<=0 or used<0 or used>total or not 0<=util<=100:raise ValueError('Invalid GPU stats')
    return {'index':index,'total_mib':total,'used_mib':used,'util_percent':util}


class GpuMonitor:
    def __init__(self):
        self.stop=threading.Event();self.samples=[];self.errors=[]
        self.thread=threading.Thread(target=self._poll,name='gpu-monitor',daemon=True)
    def _poll(self):
        while not self.stop.is_set():
            try:
                output=subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.total,memory.used,utilization.gpu','--format=csv,noheader,nounits'],text=True,timeout=5,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                self.samples.append(parse_gpu_stats(output))
            except Exception as exc:self.errors.append(str(exc))
            self.stop.wait(1.0)
    def __enter__(self):self.thread.start();return self
    def __exit__(self,*args):self.stop.set();self.thread.join(timeout=6)
    def result(self):
        if not self.samples:return {'samples':0,'monitor_errors':self.errors,'note':'No valid GPU samples; memory peak unavailable'}
        return {'samples':len(self.samples),'index':self.samples[0]['index'],'total_mib':self.samples[0]['total_mib'],
                'peak_used_mib_sampled':max(x['used_mib'] for x in self.samples),'peak_util_percent_sampled':max(x['util_percent'] for x in self.samples),
                'monitor_errors':self.errors,'note':'Whole-device polling once per second; includes other applications and can miss transient peaks.'}


def launch(config,output,runtime,*,method='baseline',frames=1,timeout=1800):
    validate_preflight(1920,1080,frames)
    if method not in ('baseline','cgns'):raise ValueError('Invalid preflight method')
    output=Path(output).resolve(); sidecar=output.parent/(output.name+'.resources.json')
    if output.exists() or sidecar.exists():raise FileExistsError('Refusing to overwrite a prior attempt')
    output.parent.mkdir(parents=True,exist_ok=True)
    started=time.monotonic();result={'status':'running','method':method,'resolution':[1920,1080],'frames':frames,'seed_policy':'fixedSeed=frame-1','output':str(output)}
    with GpuMonitor() as monitor:
        try:
            with fullhd_budget_override():
                manifest=six.launch(config,output,runtime,method=method,width=1920,height=1080,frames=frames,timeout=timeout)
            result.update(status='completed',manifest=str(manifest))
        except BaseException as exc:
            result.update(status='failed',error=str(exc))
            raise
        finally:
            result['elapsed_seconds_including_outer_checks']=time.monotonic()-started
            result['gpu_monitor']=monitor.result()
            with sidecar.open('x',encoding='utf8') as f:json.dump(result,f,indent=2,allow_nan=False)
    return sidecar


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--runtime',type=Path,required=True);p.add_argument('--method',choices=('baseline','cgns'),required=True)
    p.add_argument('--frames',type=int,choices=(1,2),default=1);p.add_argument('--timeout',type=int,default=1800)
    args=p.parse_args();print(launch(args.config,args.output,args.runtime,method=args.method,frames=args.frames,timeout=args.timeout))

if __name__=='__main__':main()
