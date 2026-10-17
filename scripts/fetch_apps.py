#!/usr/bin/env python3
"""Fetch exact official WASM releases; verify before safe extraction. Stdlib only."""
import argparse, concurrent.futures, gzip, hashlib, json, os, shutil, stat, tempfile, time, urllib.request, zipfile
from pathlib import Path, PurePosixPath

if __package__:
    from .brand_apps import ROOT, apply_branding
else:
    from brand_apps import ROOT, apply_branding


def verify_archive(path, expected):
    with Path(path).open('rb') as f: actual=hashlib.file_digest(f,'sha256').hexdigest()
    if actual != expected: raise ValueError('SHA-256 incorreto para '+Path(path).name)


def extract_bundle(archive, destination):
    destination=Path(destination)
    with zipfile.ZipFile(archive) as z:
        infos=z.infolist()
        if len(infos)>5000 or sum(x.file_size for x in infos)>2*1024**3:
            raise ValueError('Pacote excede limites de extração.')
        paths=[]
        for info in infos:
            name=info.filename
            p=PurePosixPath(name)
            mode=(info.external_attr>>16)&0o170000
            if ('\\' in name or ':' in name or p.is_absolute() or '..' in p.parts
                    or mode==stat.S_IFLNK or (mode not in (0,stat.S_IFREG,stat.S_IFDIR))):
                raise ValueError('Caminho ou tipo inseguro no ZIP.')
            paths.append(p)
        roots=[p.parent for p in paths if p.name=='index.html']
        if len(roots)!=1: raise ValueError('Pacote precisa ter um index.html inequívoco.')
        root=roots[0]
        for p in paths:
            if not p.is_relative_to(root): raise ValueError('Arquivo fora da raiz do aplicativo.')
        destination.mkdir(parents=True,exist_ok=True)
        for info,p in zip(infos,paths):
            relative=p.relative_to(root)
            if not relative.parts: continue
            target=destination.joinpath(*relative.parts)
            if info.is_dir(): target.mkdir(parents=True,exist_ok=True);continue
            target.parent.mkdir(parents=True,exist_ok=True)
            with z.open(info) as r, target.open('xb') as w: shutil.copyfileobj(r,w,1024*1024)
    return destination


def install(app, output, cache=None, precompress=True, branding_lock=ROOT/'branding.lock.json'):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fetch-'+app['id']+'-',dir=output) as tmp:
        tmp=Path(tmp);archive=tmp/'bundle.zip'
        cached=Path(cache)/app['url'].rsplit('/',1)[-1] if cache else None
        if cached and cached.is_file(): shutil.copyfile(cached,archive)
        else:
            for attempt in range(3):
                try:
                    req=urllib.request.Request(app['url'],headers={'User-Agent':'LibertyOffice/0.1 (+self-hosted)'})
                    with urllib.request.urlopen(req,timeout=90) as r, archive.open('wb') as w:
                        size=0
                        while chunk:=r.read(1024*1024):
                            size+=len(chunk)
                            if size>app['size']: raise ValueError('Download excedeu tamanho fixado.')
                            w.write(chunk)
                    if size!=app['size']: raise ValueError('Download incompleto.')
                    break
                except Exception:
                    if attempt==2: raise
                    time.sleep(attempt+1)
        verify_archive(archive,app['sha256'])
        stage=extract_bundle(archive,tmp/'extracted')
        if not list(stage.glob('*.wasm')) or not list(stage.glob('*.js')):
            raise ValueError('Pacote web sem WASM/JavaScript: '+app['id'])
        branding=apply_branding(app,stage,branding_lock)
        files={}
        for path in stage.rglob('*'):
            if not path.is_file(): continue
            with path.open('rb') as f: files[str(path.relative_to(stage))]=hashlib.file_digest(f,'sha256').hexdigest()
            if precompress and path.suffix in ('.wasm','.js') and not path.with_name(path.name+'.gz').exists():
                with path.open('rb') as r,path.with_name(path.name+'.gz').open('wb') as w:
                    with gzip.GzipFile(fileobj=w,mode='wb',compresslevel=6,mtime=0) as g: shutil.copyfileobj(r,g,1024*1024)
        (stage/'installed.json').write_text(json.dumps({'id':app['id'],'version':app['version'],'sha256':app['sha256'],'files':files,'branding':branding},indent=2))
        target=output/app['id']
        if target.exists(): shutil.rmtree(target)
        stage.rename(target)
    print(app['name']+' '+app['version']+': SHA-256 verificado e instalado',flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--lock',type=Path,default=Path(__file__).resolve().parents[1]/'upstream.lock.json')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cache',type=Path)
    p.add_argument('--no-precompress',action='store_true')
    args=p.parse_args();apps=json.loads(args.lock.read_text())['apps']
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(install,a,args.output,args.cache,not args.no_precompress) for a in apps]
        for f in futures: f.result()
    print(str(len(apps))+' aplicativos prontos. Runtime não precisa de GitHub.',flush=True)

if __name__=='__main__': main()
