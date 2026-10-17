"""Read-only diagnostics; never fabricates a production approval."""
import hashlib,json,sqlite3,shutil
from contextlib import closing
from pathlib import Path
from cryptography.fernet import Fernet

def inspect(settings,deep=False):
    checks=[]
    def add(name,ok,detail):checks.append({'name':name,'ok':bool(ok),'detail':detail})
    data=settings.data_dir
    add('isolated_origins',settings.origin!=settings.editor_origin,{'portal':settings.origin,'editors':settings.editor_origin})
    add('disk_space',shutil.disk_usage(data).free>=16*1024**2,'Minimum 16MiB free; user quota is independent.')
    try:
        with closing(sqlite3.connect((data/'liberty.db').resolve().as_uri()+'?mode=ro',uri=True)) as c:
            add('database',c.execute('PRAGMA quick_check').fetchone()[0]=='ok','SQLite quick_check')
            bad=c.execute("SELECT COUNT(*) FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.stage='full' AND u.totp_confirmed=0").fetchone()[0]
            add('mfa_sessions',bad==0,'No full session without confirmed MFA.')
            try:
                crypto=Fernet((data/'mfa.key').read_bytes())
                for row in c.execute('SELECT totp FROM users WHERE totp IS NOT NULL'):crypto.decrypt(row[0].encode())
                add('mfa_key',True,'Persistent key matches stored secrets.')
            except Exception:add('mfa_key',False,'MFA key missing or incompatible; restore original backup.')
    except sqlite3.Error:add('database',False,'Database missing, unreadable or inconsistent.')
    lock=json.loads((Path(__file__).resolve().parents[1]/'upstream.lock.json').read_text())
    for app in lock['apps']:
        directory=settings.apps_dir/app['id'];ok=False
        try:
            meta=json.loads((directory/'installed.json').read_text())
            ok=meta['sha256']==app['sha256'] and meta['version']==app['version'] and (directory/'index.html').is_file()
            if deep:
                for name,expected in meta['files'].items():
                    file=(directory/name).resolve()
                    if not file.is_relative_to(directory.resolve()) or not file.is_file():ok=False;break
                    with file.open('rb') as stream:
                        if hashlib.file_digest(stream,'sha256').hexdigest()!=expected:ok=False;break
        except (OSError,ValueError,KeyError):ok=False
        add('app:'+app['id'],ok,'Pinned release '+app['version']+(' and file digests' if deep else ''))
    return {'ok':all(x['ok'] for x in checks),'checks':checks,'production_approval':False,
            'remaining_acceptance':['Docker build/run/persistence on host','Graphical editor and import/export tests','HTTPS and backup drill on target deployment']}
