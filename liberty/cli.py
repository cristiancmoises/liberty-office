"""Local operator commands; backup/restore require an offline or empty volume."""
import argparse
from contextlib import contextmanager,closing
import fcntl,hashlib,io,json,os,re,secrets,sqlite3,sys,tarfile,tempfile
from pathlib import Path,PurePosixPath
from . import __version__
from .config import Settings
from .db import DB
from cryptography.fernet import Fernet
from .security import digest,now
from .i18n import EN

CLI_EN = {
    'Comandos locais de operação; backup/restauração exigem volume offline ou vazio.': __doc__,
    'Configuração inicial já concluída.': 'Initial setup is already complete.',
    'Entre com a senha da conta e use este código uma vez para configurar novo MFA:': 'Sign in with the account password and use this code once to set up a new MFA authenticator:',
    'Link privado de uso único, válido por 30 minutos. MFA continua obrigatório:': 'Private single-use link, valid for 30 minutes. MFA remains mandatory:',
    'Informe um caminho de saída ou --stdout.': 'Provide an output path or --stdout.',
    'Backup concluído com banco, arquivos, versões e chave MFA.': 'Backup completed with database, files, revisions, and MFA key.',
    'Backup restaurado. Sessões anteriores foram revogadas.': 'Backup restored. Previous sessions were revoked.',
    'Erro: ': 'Error: ',
    'Pare o serviço Liberty Office antes da manutenção do volume.': 'Stop Liberty Office before maintaining its volume.',
    'Volume Liberty incompleto.': 'Incomplete Liberty volume.',
    'O volume de destino deve estar vazio.': 'The destination volume must be empty.',
    'Backup contém caminhos ou tipos inválidos.': 'Backup contains invalid paths or entry types.',
    'Manifesto de backup ausente.': 'Backup manifest is missing.',
    'Manifesto de backup grande demais.': 'Backup manifest is too large.',
    'Manifesto de backup incompatível.': 'Incompatible backup manifest.',
    'Backup não contém banco e chave MFA.': 'Backup does not contain the database and MFA key.',
    'Tamanho inconsistente no backup.': 'Inconsistent size in backup.',
    'Banco do backup inconsistente.': 'Inconsistent backup database.',
    'O backup não corresponde aos blobs referenciados pelo banco.': 'Backup does not match the blobs referenced by the database.',
    'Metadados de revisão inconsistentes no backup.': 'Inconsistent revision metadata in backup.',
    'A chave MFA não corresponde às contas do backup.': 'MFA key does not match the backup accounts.',
    'Banco de contas não encontrado.': 'Account database not found.',
    'Origem inválida. Use HTTPS fora de localhost, sem caminho ou barra final.': 'Invalid origin. Use HTTPS outside localhost, without a path or trailing slash.',
    'EDITOR_ORIGIN precisa ser diferente do portal e usar o mesmo esquema HTTP/HTTPS.': 'EDITOR_ORIGIN must differ from the portal and use the same HTTP/HTTPS scheme.',
    'DEMO_EDITOR_ORIGIN precisa ser distinta do portal e dos editores privados, com o mesmo esquema.': 'DEMO_EDITOR_ORIGIN must differ from the portal and private editors, with the same scheme.',
    'Limites devem ser positivos.': 'Limits must be positive.',
}


def cli_text(message):
    """Translate fixed operator messages, not identifiers, paths or payloads."""
    if os.getenv('LIBERTY_CLI_LANGUAGE') == 'pt-BR':
        return message
    prefix = 'SHA-256 inválido no backup: '
    if message.startswith(prefix) and valid_member(message[len(prefix):]):
        return 'Invalid SHA-256 in backup: ' + message[len(prefix):]
    return CLI_EN.get(message, EN.get(message, message))

@contextmanager
def offline(data):
    data=Path(data);data.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (data/'server.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Pare o serviço Liberty Office antes da manutenção do volume.')
        try:yield
        finally:fcntl.flock(lock,fcntl.LOCK_UN)

def file_hash(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def make_backup(data,stream):
    data=Path(data)
    with offline(data):
        if not (data/'liberty.db').is_file() or not (data/'mfa.key').is_file():raise ValueError('Volume Liberty incompleto.')
        with closing(sqlite3.connect(data/'liberty.db')) as c:
            c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            ids=[row[0] for row in c.execute('SELECT id FROM versions ORDER BY id')]
        files=[Path('liberty.db'),Path('mfa.key')]+[Path('blobs')/i for i in ids]
        if (data/'bootstrap-token').is_file():files.append(Path('bootstrap-token'))
        manifest={'format':1,'version':__version__,'created':now(),'files':{str(p):{'size':(data/p).stat().st_size,'sha256':file_hash(data/p)} for p in files}}
        metadata=json.dumps(manifest,sort_keys=True,indent=2).encode()
        with tarfile.open(fileobj=stream,mode='w|gz',compresslevel=1) as archive:
            info=tarfile.TarInfo('BACKUP.json');info.size=len(metadata);info.mode=0o600;archive.addfile(info,io.BytesIO(metadata))
            for path in files:archive.add(data/path,arcname=str(path),recursive=False)
    return manifest

def valid_member(name):
    return name in ('liberty.db','mfa.key','bootstrap-token','BACKUP.json') or bool(re.fullmatch(r'blobs/[0-9a-f]{32}',name))

def restore_backup(archive_path,destination,*,preserve_sessions=False):
    if type(preserve_sessions) is not bool:raise ValueError('Invalid session preservation policy.')
    destination=Path(destination)
    with offline(destination):
        if any(p.name!='server.lock' for p in destination.iterdir()):raise ValueError('O volume de destino deve estar vazio.')
        with tempfile.TemporaryDirectory(prefix='.restore-',dir=destination) as tmp:
            stage=Path(tmp)
            incoming=None
            if hasattr(archive_path,'read'):
                incoming=stage/'.snapshot.tar.gz'
                with incoming.open('xb') as stream:
                    while chunk:=archive_path.read(1024*1024):stream.write(chunk)
                incoming.chmod(0o600)
            with tarfile.open(incoming or archive_path,'r:gz') as archive:
                members=archive.getmembers()
                names=[m.name for m in members]
                if len(names)!=len(set(names)) or any(not m.isfile() or not valid_member(m.name) for m in members):
                    raise ValueError('Backup contém caminhos ou tipos inválidos.')
                meta=archive.extractfile('BACKUP.json') if 'BACKUP.json' in names else None
                if meta is None:raise ValueError('Manifesto de backup ausente.')
                if archive.getmember('BACKUP.json').size>16*1024**2:raise ValueError('Manifesto de backup grande demais.')
                manifest=json.load(meta)
                if manifest.get('format')!=1 or set(names)!=set(manifest['files'])|{'BACKUP.json'}:
                    raise ValueError('Manifesto de backup incompatível.')
                if not {'liberty.db','mfa.key'}.issubset(manifest['files']):raise ValueError('Backup não contém banco e chave MFA.')
                for member in members:
                    if member.name=='BACKUP.json':continue
                    expected=manifest['files'][member.name]
                    if member.size!=expected['size']:raise ValueError('Tamanho inconsistente no backup.')
                    target=stage.joinpath(*PurePosixPath(member.name).parts);target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                    source=archive.extractfile(member)
                    h=hashlib.sha256()
                    with target.open('xb') as w:
                        while chunk:=source.read(1024*1024):h.update(chunk);w.write(chunk)
                    target.chmod(0o600)
                    if h.hexdigest()!=expected['sha256']:raise ValueError('SHA-256 inválido no backup: '+member.name)
            if incoming:incoming.unlink()
            # Recovery revokes sessions; only guarded current-owner migration preserves them.
            with closing(sqlite3.connect(stage/'liberty.db')) as c:
                c.execute('PRAGMA foreign_keys=ON')
                if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or c.execute('PRAGMA foreign_key_check').fetchone():
                    raise ValueError('Banco do backup inconsistente.')
                versions=c.execute('SELECT id,size,sha256 FROM versions').fetchall()
                expected_blobs={'blobs/'+row[0] for row in versions}
                if expected_blobs!={name for name in manifest['files'] if name.startswith('blobs/')}:
                    raise ValueError('O backup não corresponde aos blobs referenciados pelo banco.')
                for blob_id,size,sha in versions:
                    metadata=manifest['files']['blobs/'+blob_id]
                    if metadata['size']!=size or metadata['sha256']!=sha:
                        raise ValueError('Metadados de revisão inconsistentes no backup.')
                try:
                    crypto=Fernet((stage/'mfa.key').read_bytes())
                    for row in c.execute('SELECT totp FROM users WHERE totp IS NOT NULL'):crypto.decrypt(row[0].encode())
                except Exception:raise ValueError('A chave MFA não corresponde às contas do backup.')
                if not preserve_sessions:
                    c.execute('DELETE FROM sessions');c.execute('DELETE FROM reservations')
                c.commit()
            for item in stage.iterdir():item.rename(destination/item.name)
    return manifest

def main():
    p=argparse.ArgumentParser(description=cli_text('Comandos locais de operação; backup/restauração exigem volume offline ou vazio.'));sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('bootstrap-token');sub.add_parser('status')
    doctor=sub.add_parser('doctor');doctor.add_argument('--deep',action='store_true')
    rec=sub.add_parser('recover');rec.add_argument('username')
    reset=sub.add_parser('password-reset');reset.add_argument('username')
    back=sub.add_parser('backup');back.add_argument('--stdout',action='store_true');back.add_argument('output',nargs='?')
    restore=sub.add_parser('restore');restore.add_argument('archive');restore.add_argument('destination')
    args=p.parse_args()
    try:
        cfg=Settings.from_env()
        if args.command=='bootstrap-token':
            path=cfg.data_dir/'bootstrap-token'
            if path.is_file():print(path.read_text().strip())
            else:print(cli_text('Configuração inicial já concluída.'))
        elif args.command=='doctor':
            from scripts.check_runtime import inspect
            result=inspect(cfg,args.deep);print(json.dumps(result,indent=2));return 0 if result['ok'] else 2
        elif args.command=='status':
            with closing(sqlite3.connect((cfg.data_dir/'liberty.db').resolve().as_uri()+'?mode=ro',uri=True)) as c:
                print(json.dumps({'version':__version__,'users':c.execute('SELECT COUNT(*) FROM users').fetchone()[0],
                                 'data_bytes':c.execute('SELECT COALESCE(SUM(size),0) FROM versions').fetchone()[0],
                                 'installed_apps':len(list(cfg.apps_dir.glob('*/index.html')))},indent=2))
        elif args.command=='recover':
            code=secrets.token_urlsafe(20)
            with offline(cfg.data_dir):
                if not (cfg.data_dir/'liberty.db').is_file():raise ValueError('Banco de contas não encontrado.')
                with DB(cfg.data_dir/'liberty.db').transaction() as c:
                    row=c.execute('SELECT id FROM users WHERE username=? AND enabled=1',(args.username,)).fetchone()
                    if not row:raise ValueError('Conta ativa não encontrada.')
                    c.execute('DELETE FROM recovery WHERE user_id=?',(row['id'],))
                    c.execute('INSERT INTO recovery VALUES(?,?)',(row['id'],digest(code)))
                    c.execute('DELETE FROM sessions WHERE user_id=?',(row['id'],))
                    c.execute('INSERT INTO audit(actor,action,target,created) VALUES(NULL,?,?,?)',('operator.recover',row['id'],now()))
            print(cli_text('Entre com a senha da conta e use este código uma vez para configurar novo MFA:'))
            print(code)
        elif args.command=='password-reset':
            token=secrets.token_urlsafe(32)
            with offline(cfg.data_dir):
                if not (cfg.data_dir/'liberty.db').is_file():raise ValueError('Banco de contas não encontrado.')
                with DB(cfg.data_dir/'liberty.db').transaction() as c:
                    row=c.execute('SELECT id,password FROM users WHERE username=? AND enabled=1',(args.username,)).fetchone()
                    if not row or not row['password']:raise ValueError('Conta ativada não encontrada. Reemita o convite para contas novas.')
                    c.execute('DELETE FROM password_resets WHERE user_id=?',(row['id'],))
                    c.execute('INSERT INTO password_resets VALUES(?,?,?)',(digest(token),row['id'],now()+1800))
                    c.execute('DELETE FROM sessions WHERE user_id=?',(row['id'],))
                    c.execute('INSERT INTO audit(actor,action,target,created) VALUES(NULL,?,?,?)',('operator.password_reset',row['id'],now()))
            print(cli_text('Link privado de uso único, válido por 30 minutos. MFA continua obrigatório:'))
            print(cfg.origin+'/#reset='+token)
        elif args.command=='backup':
            if args.stdout:make_backup(cfg.data_dir,sys.stdout.buffer)
            else:
                if not args.output:raise ValueError('Informe um caminho de saída ou --stdout.')
                with Path(args.output).open('xb') as stream:make_backup(cfg.data_dir,stream)
            print(cli_text('Backup concluído com banco, arquivos, versões e chave MFA.'),file=sys.stderr)
        elif args.command=='restore':
            restore_backup(sys.stdin.buffer if args.archive=='-' else Path(args.archive),Path(args.destination));print(cli_text('Backup restaurado. Sessões anteriores foram revogadas.'))
    except (ValueError,RuntimeError,OSError,sqlite3.Error,tarfile.TarError,KeyError) as e:
        print(cli_text('Erro: ')+cli_text(str(e)),file=sys.stderr);return 1
    return 0

if __name__=='__main__':sys.exit(main())
