import os,shutil,subprocess
from pathlib import Path

def test_local_origins_update_published_ports(tmp_path):
    root=Path(__file__).resolve().parents[1]
    for name in ('libertyctl','.env.example'):shutil.copy2(root/name,tmp_path/name)
    bin=tmp_path/'bin';bin.mkdir();docker=bin/'docker';docker.write_text('#!/bin/sh\nexit 0\n');docker.chmod(0o700)
    env={**os.environ,'PATH':str(bin)+os.pathsep+os.environ['PATH']}
    subprocess.run(['./libertyctl','up','http://localhost:19097'],cwd=tmp_path,env=env,check=True,capture_output=True,text=True)
    config=dict(line.split('=',1) for line in (tmp_path/'.env').read_text().splitlines() if line and not line.startswith('#'))
    assert config['PUBLIC_ORIGIN']=='http://localhost:19097'
    assert config['EDITOR_ORIGIN']=='http://localhost:19098'
    assert config['LIBERTY_PORT']=='19097'
    assert config['EDITOR_PORT']=='19098'
    assert config['DEMO_EDITOR_ORIGIN']=='http://localhost:19099'
    assert config['DEMO_EDITOR_PORT']=='19099'
