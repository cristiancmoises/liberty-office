from dataclasses import dataclass
from ipaddress import ip_network
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
    public_assets_dir: Path | None = None
    public_signup: bool = False
    signup_quota: int = 100_000_000
    signup_attempts: int = 5
    signup_successes: int = 20
    signup_window: int = 3600
    signup_slots: int = 400
    signup_pending_ttl: int = 86400
    trusted_proxy_cidrs: tuple[str, ...] = ()
    min_free_bytes: int = 16777216

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
        if type(self.public_signup) is not bool:
            raise ValueError('PUBLIC_SIGNUP_ENABLED must be a boolean.')
        if type(self.signup_quota) is not int or not 1 <= self.signup_quota <= 2**60:
            raise ValueError('Public account quota is outside the supported range.')
        if type(self.min_free_bytes) is not int or not 1 <= self.min_free_bytes <= 2**60:
            raise ValueError('MIN_FREE_BYTES must be a positive bounded integer.')
        limits=(self.signup_attempts,self.signup_successes,self.signup_window,self.signup_slots,self.signup_pending_ttl)
        if any(type(value) is not int or not 1 <= value <= 2**31-1 for value in limits):
            raise ValueError('Signup limits must be positive bounded integers.')
        object.__setattr__(self,'trusted_proxy_cidrs',tuple(str(ip_network(value)) for value in self.trusted_proxy_cidrs))

    @property
    def secure(self):return self.origin.startswith('https:')

    @classmethod
    def from_env(cls):
        enabled=os.getenv('PUBLIC_SIGNUP_ENABLED','false').strip().lower()
        if enabled not in ('true','false','1','0','yes','no','on','off'):
            raise ValueError('Invalid PUBLIC_SIGNUP_ENABLED boolean.')
        peers=os.getenv('TRUSTED_PROXY_CIDRS','').strip()
        return cls(data_dir=Path(os.getenv('LIBERTY_DATA','/data')),apps_dir=Path(os.getenv('LIBERTY_APPS','/opt/artcraft')),
                   source_archive=Path(os.getenv('LIBERTY_SOURCE_ARCHIVE','/opt/liberty-source.zip')),
                   public_assets_dir=Path(os.environ['LIBERTY_PUBLIC_ASSETS']) if os.getenv('LIBERTY_PUBLIC_ASSETS') else None,
                   origin=os.getenv('PUBLIC_ORIGIN','http://localhost:8097'),editor_origin=os.getenv('EDITOR_ORIGIN') or None,
                   demo_editor_origin=os.getenv('DEMO_EDITOR_ORIGIN') or None,
                   global_quota=int(os.getenv('GLOBAL_QUOTA_BYTES',str(50*1024**3))),
                   default_quota=int(os.getenv('DEFAULT_QUOTA_BYTES',str(5*1024**3))),
                   max_upload=int(os.getenv('MAX_UPLOAD_BYTES',str(100*1024**2))),
                   public_signup=enabled in ('true','1','yes','on'),
                   signup_quota=int(os.getenv('PUBLIC_SIGNUP_QUOTA_BYTES','100000000')),
                   signup_attempts=int(os.getenv('SIGNUP_ATTEMPTS','5')),
                   signup_successes=int(os.getenv('SIGNUP_SUCCESSES','20')),
                   signup_window=int(os.getenv('SIGNUP_WINDOW_SECONDS','3600')),
                   signup_slots=int(os.getenv('SIGNUP_SLOTS','400')),
                   signup_pending_ttl=int(os.getenv('SIGNUP_PENDING_TTL_SECONDS','86400')),
                   trusted_proxy_cidrs=tuple(value.strip() for value in peers.split(',')) if peers else (),
                   min_free_bytes=int(os.getenv('MIN_FREE_BYTES','16777216')))
