import secrets
import sqlite3
from fastapi import APIRouter, Depends, HTTPException, Request
from .models import NewUser, UserPatch
from .security import admin, digest, now, public_user, recent, svc, uid, authorize

router=APIRouter(prefix='/api/admin')


@router.get('/users')
def users(request: Request, session=Depends(admin)):
    with svc(request).db.connect() as c:
        rows=c.execute('''SELECT u.*,COALESCE((SELECT SUM(size) FROM versions WHERE owner=u.id),0) used
                          FROM users u ORDER BY created,username''').fetchall()
    return {'users':[{**public_user(r),'used':r['used'],'activated':bool(r['password'])} for r in rows]}


@router.post('/users')
def create_user(body: NewUser, request: Request, session=Depends(admin)):
    recent(session)
    service=svc(request)
    user_id,token=uid(),secrets.token_urlsafe(32)
    try:
        with service.db.transaction() as c:
            authorize(c,session,administrator=True,fresh=True)
            c.execute('INSERT INTO users(id,username,name,role,quota,created) VALUES(?,?,?,?,?,?)',
                      (user_id,body.username,body.name,body.role,
                       body.quota if body.quota is not None else service.settings.default_quota,now()))
            c.execute('INSERT INTO invites VALUES(?,?,?)',(digest(token),user_id,now()+172800))
            row=c.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
            service.audit(c,session['user_id'],'user.create',user_id)
    except sqlite3.IntegrityError:
        raise HTTPException(409,'Nome de usuário já existe.')
    return {'user':public_user(row),'token':token,'invite_url':service.settings.origin+'/#invite='+token,'expires_in':172800}


@router.patch('/users/{user_id}')
def update_user(user_id: str, body: UserPatch, request: Request, session=Depends(admin)):
    recent(session)
    changes=body.model_dump(exclude_none=True)
    if user_id==session['user_id'] and (changes.get('enabled') is False or changes.get('role')=='user'):
        raise HTTPException(409,'Você não pode desativar ou remover seu próprio papel de administrador.')
    service=svc(request)
    with service.db.transaction() as c:
        authorize(c,session,administrator=True,fresh=True)
        if not c.execute('SELECT id FROM users WHERE id=?',(user_id,)).fetchone():
            raise HTTPException(404,'Conta não encontrada.')
        if changes:
            c.execute('UPDATE users SET '+','.join(k+'=?' for k in changes)+' WHERE id=?',(*changes.values(),user_id))
        if 'enabled' in changes or 'role' in changes:
            c.execute('DELETE FROM sessions WHERE user_id=?',(user_id,))
        service.audit(c,session['user_id'],'user.update',user_id)
    return {'ok':True}


@router.get('/audit')
def audit(request: Request, session=Depends(admin)):
    with svc(request).db.connect() as c:
        rows=c.execute('''SELECT a.*,u.username FROM audit a LEFT JOIN users u ON a.actor=u.id
                          ORDER BY a.id DESC LIMIT 200''').fetchall()
    return {'events':[dict(r) for r in rows]}


@router.post('/users/{user_id}/invite')
def reissue_invite(user_id: str, request: Request, session=Depends(admin)):
    service=svc(request);token=secrets.token_urlsafe(32)
    with service.db.transaction() as c:
        authorize(c,session,administrator=True,fresh=True)
        user=c.execute('SELECT * FROM users WHERE id=? AND enabled=1',(user_id,)).fetchone()
        if not user:raise HTTPException(404,'Conta ativa não encontrada.')
        if user['password']:raise HTTPException(409,'Esta conta já foi ativada. Use recuperação de senha.')
        c.execute('DELETE FROM invites WHERE user_id=?',(user_id,))
        c.execute('INSERT INTO invites VALUES(?,?,?)',(digest(token),user_id,now()+172800))
        service.audit(c,session['user_id'],'invite.reissue',user_id)
    return {'token':token,'invite_url':service.settings.origin+'/#invite='+token,'expires_in':172800}


@router.post('/users/{user_id}/password-reset')
def reset_password(user_id: str, request: Request, session=Depends(admin)):
    service=svc(request);token=secrets.token_urlsafe(32)
    with service.db.transaction() as c:
        authorize(c,session,administrator=True,fresh=True)
        user=c.execute('SELECT * FROM users WHERE id=? AND enabled=1',(user_id,)).fetchone()
        if not user:raise HTTPException(404,'Conta ativa não encontrada.')
        if not user['password']:
            raise HTTPException(409,'Reemita o convite para esta conta ainda não ativada.')
        c.execute('DELETE FROM password_resets WHERE user_id=?',(user_id,))
        c.execute('INSERT INTO password_resets VALUES(?,?,?)',(digest(token),user_id,now()+1800))
        c.execute('DELETE FROM sessions WHERE user_id=?',(user_id,))
        service.audit(c,session['user_id'],'password.reset.issue',user_id)
    return {'token':token,'reset_url':service.settings.origin+'/#reset='+token,'expires_in':1800}
