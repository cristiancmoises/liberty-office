#!/usr/bin/env python3
"""Destructive only to a NEW empty acceptance instance. Never runs on initialized data."""
import argparse,http.cookiejar,json,os,secrets,sys,urllib.request,urllib.error
from pathlib import Path
from urllib.parse import urlsplit
import pyotp
from liberty.config import Settings


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transport',default='http://127.0.0.1:8097')
    parser.add_argument('--seed',default='/data/tmp/acceptance-seed.json')
    parser.add_argument('--verify-restored',action='store_true',help='Verify only a restored disposable test snapshot using its synthetic seed.')
    args=parser.parse_args();cfg=Settings.from_env();jar=http.cookiejar.CookieJar();opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    csrf='';passed=[]
    def call(method,path,body=None,headers=None,expected=200,origin=None,raw=False):
        origin=origin or cfg.origin;request_headers={'Host':urlsplit(origin).netloc,'Origin':cfg.origin}
        if csrf:request_headers['X-CSRF-Token']=csrf
        if isinstance(body,dict):body=json.dumps(body).encode();request_headers['Content-Type']='application/json'
        request_headers.update(headers or {})
        req=urllib.request.Request(args.transport+path,data=body,headers=request_headers,method=method)
        try:response=opener.open(req,timeout=60)
        except urllib.error.HTTPError as e:response=e
        if response.code!=expected:raise RuntimeError(method+' '+path.split('?')[0]+' returned '+str(response.code)+' expected '+str(expected))
        data=response.read();return data if raw else json.loads(data)
    status=call('GET','/api/auth/status')
    if args.verify_restored:
        if status['setup_required']:raise RuntimeError('Restored snapshot unexpectedly requires bootstrap.')
        seed=json.load(sys.stdin) if args.seed=='-' else json.loads(Path(args.seed).read_text())
        call('POST','/api/auth/login',{'username':seed['username'],'password':seed['password']})
        csrf=call('GET','/api/auth/status')['csrf']
        # A still-unused test recovery code avoids reusing an enrollment TOTP.
        assert call('POST','/api/auth/mfa/verify',{'code':seed['recovery']})['state']=='enroll'
        csrf=call('GET','/api/auth/status')['csrf'];call('GET','/api/files',expected=403)
        setup=call('GET','/api/auth/mfa/setup')
        assert call('POST','/api/auth/mfa/verify',{'code':pyotp.TOTP(setup['secret']).now()})['state']=='full'
        csrf=call('GET','/api/auth/status')['csrf']
        assert call('GET','/api/files/'+seed['file']+'/content',raw=True)==b'Liberty acceptance data'
        assert call('GET','/api/files/'+seed['file']+'/content?version='+seed['old_version'],raw=True)==b'Liberty acceptance data'
        print(json.dumps({'passed':['restored login, mandatory MFA and recovery','current content and historical revision from restored volume']},indent=2));return 0
    if not status['setup_required']:raise RuntimeError('REFUSED: use a new empty test volume, never an existing deployment.')
    password='Acceptance-only-password-'+secrets.token_urlsafe(18)
    token=(cfg.data_dir/'bootstrap-token').read_text().strip()
    call('POST','/api/auth/bootstrap',{'token':token,'username':'acceptance','name':'Acceptance test','password':password})
    csrf=call('GET','/api/auth/status')['csrf']
    call('GET','/api/files',expected=403);setup=call('GET','/api/auth/mfa/setup')
    result=call('POST','/api/auth/mfa/verify',{'code':pyotp.TOTP(setup['secret']).now()})
    csrf=call('GET','/api/auth/status')['csrf'];passed.append('bootstrap and mandatory MFA')
    apps=call('GET','/api/apps')['apps'];assert len(apps)==13 and all(a['installed'] for a in apps)
    for app in apps:
        ticket=call('POST',app['launch_url']);path=urlsplit(ticket['url']).path
        html=call('GET',path,origin=cfg.editor_origin,raw=True)
        assert b'__liberty-config' in html and csrf.encode() not in html
        assert b'application/x-liberty-module' in html
        call('GET','/api/auth/status',origin=cfg.editor_origin,expected=404)
        root=path.rsplit('/',1)[0];call('GET',root+'/__liberty/editor-host.mjs',origin=cfg.editor_origin,raw=True)
        call('DELETE','/api/editors/'+ticket['ticket_id'])
        call('GET',path,origin=cfg.editor_origin,expected=401)
    passed.append('13 isolated editors, scoped tickets and revocation')
    file=call('POST','/api/files?name=acceptance-persist.txt',b'Liberty acceptance data')
    assert call('GET','/api/files/'+file['id']+'/content',raw=True)==b'Liberty acceptance data'
    updated=call('PUT','/api/files/'+file['id']+'/content',b'Liberty revised',headers={'If-Match':file['etag']})
    call('PUT','/api/files/'+file['id']+'/content',b'stale',headers={'If-Match':file['etag']},expected=412)
    restored=call('POST','/api/files/'+file['id']+'/versions/'+file['version']+'/restore',headers={'If-Match':updated['etag']})
    assert call('GET','/api/files/'+file['id']+'/content',raw=True)==b'Liberty acceptance data'
    call('DELETE','/api/files/'+file['id']);call('POST','/api/files/'+file['id']+'/restore')
    passed.append('stream upload, revisions, ETag, trash and restore')
    call('GET','/source.zip',raw=True);passed.append('AGPL source offer')
    seed={'origin':cfg.origin,'editorOrigin':cfg.editor_origin,'username':'acceptance','password':password,
          'recovery':result['recovery_codes'][0],'file':restored['id'],'old_version':file['version']}
    path=Path(args.seed);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(seed));path.chmod(0o600)
    print(json.dumps({'passed':passed,'apps':13,'graphical_tests':'not run by this API script'},indent=2))
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except Exception as e:print('Acceptance failed: '+str(e),file=sys.stderr);sys.exit(1)
