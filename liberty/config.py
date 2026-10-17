from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlsplit


def canonical_origin(value):
    try:
        p=urlsplit(value)
        port=p.port
        if (p.scheme not in ('http','https') or not p.hostname or p.username or p.password
                or p.path or p.query or p.fragment or any(ch.isspace() for ch in value)):
            raise ValueError()
        if p.scheme=='http' and p.hostname not in ('localhost','127.0.0.1','::1'):
            raise ValueError('HTTPS obrigatório fora de localhost.')
        if port is not None and not 1<=port<=65535:raise ValueError()
        host=p.hostname.encode('idna').decode('ascii').lower()
        if ':' in host:host='['+host+']'
        suffix=':'+str(port) if port and port!=({'http':80,'https':443}[p.scheme]) else ''
        return p.scheme+'://'+host+suffix
    except (ValueError,UnicodeError):
        raise ValueError('Origem inválida. Use HTTPS fora de localhost, sem caminho ou barra final.')


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path('/data')
    apps_dir: Path = Path('/opt/artcraft')
    source_archive: Path = Path('/opt/liberty-source.zip')
    origin: str = 'http://localhost:8097'
    editor_origin: str | None = None
    demo_editor_origin: str | None = None
    global_quota: int = 50*1024**3
    default_quota: int = 5*1024**3
    max_upload: int = 100*1024**2
    session_seconds: int = 43200

    def __post_init__(self):
        origin=canonical_origin(self.origin);object.__setattr__(self,'origin',origin)
        p=urlsplit(origin)
        editor=self.editor_origin
        if not editor:
            if p.hostname in ('localhost','127.0.0.1','::1'):
                host='['+p.hostname+']' if ':' in p.hostname else p.hostname
                editor=p.scheme+'://'+host+':'+str((p.port or (443 if p.scheme=='https' else 80))+1)
            else:editor=p.scheme+'://edit.'+p.hostname+(':'+str(p.port) if p.port else '')
        editor=canonical_origin(editor);object.__setattr__(self,'editor_origin',editor)
        if editor==origin or urlsplit(editor).scheme!=p.scheme:
            raise ValueError('EDITOR_ORIGIN precisa ser diferente do portal e usar o mesmo esquema HTTP/HTTPS.')
        demo=self.demo_editor_origin
        if not demo:
            if p.hostname in ('localhost','127.0.0.1','::1'):
                host='['+p.hostname+']' if ':' in p.hostname else p.hostname
                demo=p.scheme+'://'+host+':'+str((p.port or (443 if p.scheme=='https' else 80))+2)
            else:
                demo=p.scheme+'://demo-edit.'+p.hostname+(':'+str(p.port) if p.port else '')
        demo=canonical_origin(demo);object.__setattr__(self,'demo_editor_origin',demo)
        if demo in (origin,editor) or urlsplit(demo).scheme!=p.scheme:
            raise ValueError('DEMO_EDITOR_ORIGIN precisa ser distinta do portal e dos editores privados, com o mesmo esquema.')
        if min(self.global_quota,self.default_quota,self.max_upload,self.session_seconds)<=0:
            raise ValueError('Limites devem ser positivos.')

    @property
    def secure(self):return self.origin.startswith('https:')

    @classmethod
    def from_env(cls):
        return cls(data_dir=Path(os.getenv('LIBERTY_DATA','/data')),apps_dir=Path(os.getenv('LIBERTY_APPS','/opt/artcraft')),
                   source_archive=Path(os.getenv('LIBERTY_SOURCE_ARCHIVE','/opt/liberty-source.zip')),
                   origin=os.getenv('PUBLIC_ORIGIN','http://localhost:8097'),editor_origin=os.getenv('EDITOR_ORIGIN') or None,
                   demo_editor_origin=os.getenv('DEMO_EDITOR_ORIGIN') or None,
                   global_quota=int(os.getenv('GLOBAL_QUOTA_BYTES',str(50*1024**3))),
                   default_quota=int(os.getenv('DEFAULT_QUOTA_BYTES',str(5*1024**3))),
                   max_upload=int(os.getenv('MAX_UPLOAD_BYTES',str(100*1024**2))))
