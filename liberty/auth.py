import secrets
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response
import pyotp
import qrcode
import qrcode.image.svg

from .models import Activate, Bootstrap, Code, Login, Password, PublicSignup, Reauth
from .signup import signup, signup_source
from .security import (COOKIE, PH, check_password, digest, full, now, pending,
                       public_user, svc, totp_step, uid, hash_password, authorize, recent)

router = APIRouter(prefix='/api/auth')


@router.get('/status')
def status(request: Request):
    service = svc(request)
    session = service.session(request)
    with service.db.connect() as c:
        setup = c.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0
        registration = service.settings.public_signup and bool(c.execute("SELECT 1 FROM users WHERE role='admin' AND enabled=1 AND totp_confirmed=1 LIMIT 1").fetchone())
    result = {'state':session['stage'] if session else 'anonymous','setup_required':setup,
              'public_signup':registration,'signup_quota_bytes':service.settings.signup_quota}
    if session:
        result['csrf'] = session['csrf']
        if session['stage'] == 'full':
            result['user'] = {**public_user({**session,'id':session['user_id']}), 'enabled':True}
    return result


@router.post('/bootstrap')
def bootstrap(body: Bootstrap, request: Request, response: Response):
    service=svc(request)
    service.limit('bootstrap',10)
    path=service.settings.data_dir/'bootstrap-token'
    with service.db.transaction() as c:
        if c.execute('SELECT COUNT(*) FROM users').fetchone()[0]:
            raise HTTPException(409,'A configuração inicial já foi concluída.')
        if not path.exists() or not secrets.compare_digest(path.read_text().strip(),body.token):
            raise HTTPException(401,'Token inicial inválido.')
        user_id=uid()
        c.execute('''INSERT INTO users(id,username,name,password,role,quota,totp,created)
            VALUES(?,?,?,?,?,?,?,?)''',(user_id,body.username,body.name,hash_password(body.password),
                'admin',service.settings.default_quota,service.new_secret(),now()))
        service.new_session(c,user_id,'enroll',response)
        service.audit(c,user_id,'bootstrap')
    path.unlink(missing_ok=True)
    return {'state':'enroll'}


@router.post('/login')
def login(body: Login, request: Request, response: Response):
    service=svc(request)
    name=body.username.strip().lower()
    service.limit('ip:'+request.client.host,120)
    service.limit('login:'+name,10)
    with service.db.connect() as c:
        user=c.execute('SELECT * FROM users WHERE username=?',(name,)).fetchone()
    valid=check_password(user['password'] if user else None,body.password)
    if not user or not valid or not user['enabled']:
        raise HTTPException(401,'Usuário ou senha inválidos.')
    with service.db.transaction() as c:
        # A disabled account cannot create a session through a racing login.
        current=c.execute('SELECT * FROM users WHERE id=?',(user['id'],)).fetchone()
        if not current['enabled'] or current['password']!=user['password']:
            raise HTTPException(401,'Usuário ou senha inválidos.')
        if request.cookies.get(COOKIE):
            c.execute('DELETE FROM sessions WHERE id=?',(digest(request.cookies[COOKIE]),))
        stage='mfa' if current['totp_confirmed'] else 'enroll'
        service.new_session(c,user['id'],stage,response)
    return {'state':stage}


@router.post('/signup',status_code=201)
def public_signup(body: PublicSignup, request: Request, response: Response):
    service=svc(request)
    cfg=service.settings
    if not cfg.public_signup:
        raise HTTPException(503,'Public registration is not available.')
    # This independently committed counter must survive rejected transactions.
    source=digest(signup_source(request,cfg))
    service.limit('signup:source:'+source,cfg.signup_attempts,cfg.signup_window)
    with service.db.transaction() as c:
        return signup(c,service,body,response)


@router.post('/activate')
def activate(body: Activate, request: Request, response: Response):
    service=svc(request)
    service.limit('activate:'+request.client.host,20)
    with service.db.transaction() as c:
        invitation=c.execute('SELECT * FROM invites WHERE digest=? AND expires>?',
                              (digest(body.token),now())).fetchone()
        if not invitation:
            raise HTTPException(401,'Convite inválido ou expirado.')
        user=c.execute('SELECT * FROM users WHERE id=?',(invitation['user_id'],)).fetchone()
        if not user or not user['enabled'] or user['password']:
            raise HTTPException(401,'Convite inválido ou expirado.')
        c.execute('UPDATE users SET password=?,totp=?,totp_confirmed=0,totp_step=-1 WHERE id=?',
                  (hash_password(body.password),service.new_secret(),user['id']))
        c.execute('DELETE FROM invites WHERE user_id=?',(user['id'],))
        service.new_session(c,user['id'],'enroll',response)
        service.audit(c,user['id'],'invite.activate')
    return {'state':'enroll'}


@router.get('/mfa/setup')
def mfa_setup(request: Request, session=Depends(pending)):
    if session['stage']!='enroll' or session['totp_confirmed']:
        raise HTTPException(403,'Configuração MFA indisponível nesta sessão.')
    service=svc(request)
    with service.db.connect() as c:
        user=c.execute('SELECT * FROM users WHERE id=?',(session['user_id'],)).fetchone()
    if not user or user['totp_confirmed']:
        raise HTTPException(403,'A configuração MFA já foi concluída.')
    secret=service.secret(user['totp'])
    uri=pyotp.TOTP(secret).provisioning_uri(user['username'],issuer_name='Liberty Office')
    qr=qrcode.make(uri,image_factory=qrcode.image.svg.SvgPathImage)
    return {'secret':secret,'uri':uri,'qr_svg':qr.to_string(encoding='unicode')}


@router.post('/mfa/verify')
def mfa_verify(body: Code, request: Request, response: Response, session=Depends(pending)):
    service=svc(request)
    if session['stage'] not in ('mfa','enroll'):
        raise HTTPException(409,'MFA já confirmado.')
    service.limit('mfa:'+session['user_id'],15)
    with service.db.transaction() as c:
        # Re-check the challenge under the same lock as the one-use factor.
        challenge=c.execute('SELECT * FROM sessions WHERE id=? AND expires>?',(session['id'],now())).fetchone()
        if not challenge:
            raise HTTPException(401,'Sessão expirada.')
        user=c.execute('SELECT * FROM users WHERE id=? AND enabled=1',(session['user_id'],)).fetchone()
        if not user:
            raise HTTPException(401,'Sessão expirada.')
        if session['stage']=='enroll' and user['totp_confirmed']:
            raise HTTPException(403,'A configuração MFA já foi concluída.')
        step=totp_step(service,user,body.code.strip())
        if step is None:
            if session['stage']=='mfa':
                code=digest(body.code.strip())
                found=c.execute('DELETE FROM recovery WHERE user_id=? AND digest=?', (user['id'],code)).rowcount
                if found:
                    c.execute('UPDATE users SET totp=?,totp_confirmed=0,totp_step=-1 WHERE id=?',
                              (service.new_secret(),user['id']))
                    c.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
                    service.new_session(c,user['id'],'enroll',response)
                    service.audit(c,user['id'],'mfa.recover')
                    return {'state':'enroll'}
            raise HTTPException(401,'Código inválido, expirado ou já utilizado.')
        c.execute('UPDATE users SET totp_confirmed=1,totp_step=? WHERE id=?',(step,user['id']))
        c.execute('UPDATE public_accounts SET established_at=COALESCE(established_at,?) WHERE user_id=?',(now(),user['id']))
        c.execute('DELETE FROM sessions WHERE id=?',(session['id'],))
        result={'state':'full'}
        if session['stage']=='enroll':
            c.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
            codes=[secrets.token_urlsafe(15) for _ in range(10)]
            c.execute('DELETE FROM recovery WHERE user_id=?',(user['id'],))
            c.executemany('INSERT INTO recovery VALUES(?,?)',[(user['id'],digest(code)) for code in codes])
            result['recovery_codes']=codes
        service.new_session(c,user['id'],'full',response)
        service.audit(c,user['id'],'mfa.verify')
    return result


@router.post('/reauth')
def reauth(body: Reauth, request: Request, session=Depends(full)):
    service=svc(request)
    service.limit('reauth:'+session['user_id'],10)
    with service.db.transaction() as c:
        authorize(c,session)
        user=c.execute('SELECT * FROM users WHERE id=?',(session['user_id'],)).fetchone()
        if not check_password(user['password'],body.password):
            raise HTTPException(401,'Senha ou código inválidos.')
        step=totp_step(service,user,body.code)
        if step is None:
            raise HTTPException(401,'Senha ou código inválidos. Use um código novo.')
        c.execute('UPDATE users SET totp_step=? WHERE id=?',(step,user['id']))
        c.execute('UPDATE sessions SET auth_at=? WHERE id=?',(now(),session['id']))
    return {'ok':True}


@router.post('/password')
def change_password(body: Password, request: Request, session=Depends(full)):
    service=svc(request)
    service.limit('password:'+session['user_id'],10)
    with service.db.transaction() as c:
        authorize(c,session,fresh=True)
        user=c.execute('SELECT password FROM users WHERE id=?',(session['user_id'],)).fetchone()
        if not check_password(user['password'],body.current_password):
            raise HTTPException(401,'Senha atual inválida.')
        c.execute('UPDATE users SET password=? WHERE id=?',(hash_password(body.password),session['user_id']))
        c.execute('DELETE FROM sessions WHERE user_id=? AND id<>?',(session['user_id'],session['id']))
        service.audit(c,session['user_id'],'password.change')
    return {'ok':True}


@router.post('/logout')
def logout(request: Request, response: Response, session=Depends(pending)):
    with svc(request).db.transaction() as c:
        c.execute('DELETE FROM sessions WHERE id=?',(session['id'],))
    response.delete_cookie(COOKIE,path='/',secure=svc(request).settings.secure,httponly=True,samesite='strict')
    response.headers['Clear-Site-Data']='"cache", "storage"'
    return {'ok':True}


@router.post('/password-reset')
def consume_password_reset(body: Activate, request: Request, response: Response):
    service=svc(request);service.limit('reset:'+request.client.host,15)
    password=hash_password(body.password)
    with service.db.transaction() as c:
        token=c.execute('SELECT * FROM password_resets WHERE digest=? AND expires>?',(digest(body.token),now())).fetchone()
        user=c.execute('SELECT * FROM users WHERE id=? AND enabled=1',(token['user_id'],)).fetchone() if token else None
        if not user or not user['password']:
            raise HTTPException(401,'Link de recuperação inválido ou expirado.')
        c.execute('UPDATE users SET password=? WHERE id=?',(password,user['id']))
        stage='mfa' if user['totp_confirmed'] else 'enroll'
        if stage=='enroll':
            c.execute('UPDATE users SET totp=?,totp_step=-1 WHERE id=?',(service.new_secret(),user['id']))
            c.execute('DELETE FROM recovery WHERE user_id=?',(user['id'],))
        c.execute('DELETE FROM password_resets WHERE user_id=?',(user['id'],))
        c.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
        service.new_session(c,user['id'],stage,response)
        service.audit(c,user['id'],'password.reset.complete')
    return {'state':stage}


@router.get('/sessions')
def sessions(request: Request, session=Depends(full)):
    with svc(request).db.connect() as c:
        rows=c.execute("SELECT id,auth_at,expires FROM sessions WHERE user_id=? AND stage='full' AND expires>? ORDER BY auth_at DESC",(session['user_id'],now())).fetchall()
    return {'sessions':[{**dict(r),'current':r['id']==session['id']} for r in rows]}


@router.delete('/sessions/{session_id}')
def revoke_session(session_id: str, request: Request, response: Response, session=Depends(full)):
    service=svc(request)
    with service.db.transaction() as c:
        authorize(c,session,fresh=True)
        if not c.execute('DELETE FROM sessions WHERE id=? AND user_id=?',(session_id,session['user_id'])).rowcount:
            raise HTTPException(404,'Sessão não encontrada.')
        service.audit(c,session['user_id'],'session.revoke')
    if session_id==session['id']:response.delete_cookie(COOKIE,path='/',secure=service.settings.secure,httponly=True,samesite='strict')
    return {'ok':True}


@router.delete('/sessions')
def revoke_other_sessions(request: Request, session=Depends(full)):
    service=svc(request)
    with service.db.transaction() as c:
        authorize(c,session,fresh=True)
        count=c.execute('DELETE FROM sessions WHERE user_id=? AND id<>?',(session['user_id'],session['id'])).rowcount
        service.audit(c,session['user_id'],'sessions.revoke_others')
    return {'revoked':count}
