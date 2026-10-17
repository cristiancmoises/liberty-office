"""Private, versioned blobs with transactional quota reservations."""
import asyncio
import hashlib
import os
import shutil
import sqlite3
import unicodedata
from urllib.parse import quote
import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import Field, field_validator
from .models import Model
from .security import full, now, svc, uid, authorize

router=APIRouter()

def safe_name(value):
    value=unicodedata.normalize('NFC',value.strip())
    if (not value or len(value)>180 or value in ('.','..') or any(ch in value for ch in '/\\')
            or any(unicodedata.category(ch) in ('Cc','Cf','Cs') for ch in value)):
        raise ValueError('Nome inválido. Use até 180 caracteres, sem caminhos ou controles.')
    return value

class Folder(Model):
    name: str
    parent: str | None = None
    _name=field_validator('name')(safe_name)

class EntryPatch(Model):
    name: str | None = None
    parent: str | None = None
    @field_validator('name')
    @classmethod
    def valid(cls,v):
        return safe_name(v) if v is not None else v

class Share(Model):
    username: str = Field(min_length=3,max_length=48)

def owned(c, entry_id, owner, live=True):
    row=c.execute('SELECT * FROM entries WHERE id=? AND owner=?', (entry_id,owner)).fetchone()
    if not row or (live and row['trash']):
        raise HTTPException(404,'Arquivo ou pasta não encontrado.')
    return row

def parent_folder(c, parent, owner):
    if parent and owned(c,parent,owner)['kind']!='folder':
        raise HTTPException(422,'O destino precisa ser uma pasta.')

def latest(c, entry_id):
    return c.execute('SELECT * FROM versions WHERE entry_id=? ORDER BY sequence DESC LIMIT 1',(entry_id,)).fetchone()

def present(c, row):
    result=dict(row)
    v=latest(c,row['id']) if row['kind']=='file' else None
    result.update(size=v['size'] if v else 0,etag='"'+v['id']+'"' if v else None,version=v['id'] if v else None)
    return result

def usage(c, owner=None):
    clause=' WHERE owner=?' if owner else '';params=(owner,) if owner else ()
    used=c.execute('SELECT COALESCE(SUM(size),0) FROM versions'+clause,params).fetchone()[0]
    reserved=c.execute('SELECT COALESCE(SUM(size),0) FROM reservations'+clause,params).fetchone()[0]
    return used,reserved

@router.get('/api/storage')
def storage(request: Request, session=Depends(full)):
    service=svc(request)
    with service.db.connect() as c:
        used,reserved=usage(c,session['user_id'])
        result={'used':used,'reserved':reserved,'quota':session['quota'],'max_upload':service.settings.max_upload}
        if session['role']=='admin':
            total,pending=usage(c)
            result.update(global_used=total,global_reserved=pending,global_quota=service.settings.global_quota,
                          disk_free=shutil.disk_usage(service.settings.data_dir).free)
    return result

@router.get('/api/files')
def list_files(request: Request, parent: str | None=None, view: str='drive', session=Depends(full)):
    with svc(request).db.connect() as c:
        breadcrumbs=[]
        if view=='shared':
            rows=c.execute('''SELECT e.*,u.username owner_username FROM entries e JOIN shares s ON e.id=s.entry_id
                JOIN users u ON e.owner=u.id WHERE s.recipient=? AND e.trash IS NULL ORDER BY e.name''',(session['user_id'],)).fetchall()
        elif view=='recent':
            rows=c.execute("SELECT * FROM entries WHERE owner=? AND kind='file' AND trash IS NULL ORDER BY updated DESC,id LIMIT 12",(session['user_id'],)).fetchall()
        elif view=='trash':
            rows=c.execute('SELECT * FROM entries WHERE owner=? AND trash=id ORDER BY updated DESC',(session['user_id'],)).fetchall()
        elif view=='drive':
            parent_folder(c,parent,session['user_id'])
            rows=c.execute('''SELECT * FROM entries WHERE owner=? AND parent IS ? AND trash IS NULL
                ORDER BY kind DESC,name COLLATE NOCASE''',(session['user_id'],parent)).fetchall()
            cursor=parent
            while cursor:
                row=owned(c,cursor,session['user_id']);breadcrumbs.insert(0,{'id':row['id'],'name':row['name']});cursor=row['parent']
        else:
            raise HTTPException(422,'Visualização inválida.')
        return {'files':[present(c,row) for row in rows],'breadcrumbs':breadcrumbs}

@router.post('/api/folders')
def create_folder(body: Folder, request: Request, session=Depends(full)):
    service=svc(request);entry_id=uid()
    try:
        with service.db.transaction() as c:
            authorize(c,session)
            parent_folder(c,body.parent,session['user_id'])
            c.execute('INSERT INTO entries VALUES(?,?,?,?,?,?,?,?)',
                      (entry_id,session['user_id'],body.parent,body.name,'folder',None,now(),now()))
            return present(c,owned(c,entry_id,session['user_id']))
    except sqlite3.IntegrityError:
        raise HTTPException(409,'Já existe um item com esse nome nesta pasta.')

def reserve(service, session, length):
    if length<0: raise HTTPException(400,'Content-Length inválido.')
    if length>service.settings.max_upload: raise HTTPException(413,'Arquivo excede o limite por envio.')
    reservation=uid()
    with service.db.transaction() as c:
        authorize(c,session)
        user=c.execute('SELECT * FROM users WHERE id=? AND enabled=1',(session['user_id'],)).fetchone()
        if not user: raise HTTPException(401,'Conta indisponível.')
        used,pending=usage(c,session['user_id']);total,all_pending=usage(c)
        if used+pending+length>user['quota'] or total+all_pending+length>service.settings.global_quota:
            raise HTTPException(413,'Espaço insuficiente na cota. Versões e lixeira também ocupam espaço.')
        if c.execute('SELECT COUNT(*) FROM reservations WHERE owner=?',(user['id'],)).fetchone()[0]>=3:
            raise HTTPException(429,'Aguarde a conclusão dos envios em andamento.')
        if shutil.disk_usage(service.settings.data_dir).free<all_pending+length+16*1024**2:
            raise HTTPException(507,'O disco do servidor não tem espaço livre suficiente.')
        c.execute('INSERT INTO reservations VALUES(?,?,?,?)',(reservation,user['id'],length,now()))
    return reservation

async def write_upload(request, session, name=None, parent=None, entry_id=None):
    service=svc(request)
    try: size=int(request.headers['content-length'])
    except (KeyError,ValueError): raise HTTPException(411,'Content-Length é obrigatório para aplicar cotas antes do envio.')
    try:
        if name is not None: name=safe_name(name)
    except ValueError as e: raise HTTPException(422,str(e))
    expected=request.headers.get('if-match')
    with service.db.connect() as c:
        if entry_id:
            entry=owned(c,entry_id,session['user_id'])
            if entry['kind']!='file': raise HTTPException(422,'Este item não é um arquivo.')
            if expected is None: raise HTTPException(428,'If-Match é obrigatório para preservar revisões concorrentes.')
            if expected!='"'+latest(c,entry_id)['id']+'"': raise HTTPException(412,'O arquivo mudou. Abra a versão atual antes de salvar.')
        else:
            parent_folder(c,parent,session['user_id'])
            if c.execute('SELECT id FROM entries WHERE owner=? AND parent IS ? AND name=? AND trash IS NULL',
                         (session['user_id'],parent,name)).fetchone():
                raise HTTPException(409,'Já existe um item com esse nome nesta pasta.')
    reservation=reserve(service,session,size)
    temp=service.settings.data_dir/'tmp'/reservation;blob=service.settings.data_dir/'blobs'/reservation;published=False
    try:
        h=hashlib.sha256();count=0
        async with await anyio.open_file(temp,'xb') as f:
            async with asyncio.timeout(300):
                async for chunk in request.stream():
                    count+=len(chunk)
                    if count>size: raise HTTPException(400,'O corpo excede o Content-Length declarado.')
                    h.update(chunk);await f.write(chunk)
                await f.flush()
        if count!=size: raise HTTPException(400,'Envio incompleto: Content-Length não corresponde ao corpo.')
        with temp.open('rb') as durable:
            await anyio.to_thread.run_sync(os.fsync,durable.fileno())
        try:
            with service.db.transaction() as c:
                authorize(c,session)
                active=c.execute('''SELECT s.id FROM sessions s JOIN users u ON u.id=s.user_id
                    WHERE s.id=? AND s.stage='full' AND s.expires>? AND u.enabled=1''',(session['id'],now())).fetchone()
                if not active: raise HTTPException(401,'Sessão expirada durante o envio.')
                user=c.execute('SELECT quota FROM users WHERE id=?',(session['user_id'],)).fetchone()
                used,pending=usage(c,session['user_id'])
                if used+pending>user['quota']: raise HTTPException(413,'A cota foi alterada durante o envio.')
                if entry_id:
                    owned(c,entry_id,session['user_id']);v=latest(c,entry_id)
                    if expected!='"'+v['id']+'"': raise HTTPException(412,'Outra revisão foi salva durante o envio.')
                    sequence=v['sequence']+1
                else:
                    parent_folder(c,parent,session['user_id']);entry_id=uid();sequence=1
                    c.execute('INSERT INTO entries VALUES(?,?,?,?,?,?,?,?)',
                              (entry_id,session['user_id'],parent,name,'file',None,now(),now()))
                temp.replace(blob)
                directory=os.open(blob.parent,os.O_RDONLY|os.O_DIRECTORY)
                try:os.fsync(directory)
                finally:os.close(directory)
                c.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?)',(reservation,entry_id,session['user_id'],count,h.hexdigest(),now(),sequence))
                c.execute('UPDATE entries SET updated=? WHERE id=?',(now(),entry_id))
                c.execute('DELETE FROM reservations WHERE id=?',(reservation,))
                service.audit(c,session['user_id'],'file.save',entry_id)
                result=present(c,owned(c,entry_id,session['user_id']))
            published=True
            return result
        except sqlite3.IntegrityError: raise HTTPException(409,'Já existe um item com esse nome nesta pasta.')
    except TimeoutError: raise HTTPException(408,'O envio excedeu cinco minutos. Tente novamente.')
    finally:
        temp.unlink(missing_ok=True)
        if not published: blob.unlink(missing_ok=True)
        with service.db.transaction() as c: c.execute('DELETE FROM reservations WHERE id=?',(reservation,))

@router.post('/api/files')
async def upload(request: Request, name: str, parent: str | None=None, session=Depends(full)):
    return await write_upload(request,session,name,parent)

@router.put('/api/files/{entry_id}/content')
async def update_content(entry_id: str, request: Request, session=Depends(full)):
    return await write_upload(request,session,entry_id=entry_id)

def readable(c, entry_id, owner):
    row=c.execute('SELECT * FROM entries WHERE id=?',(entry_id,)).fetchone()
    if row and row['owner']==owner: return row
    if row and not row['trash'] and c.execute('SELECT 1 FROM shares WHERE entry_id=? AND recipient=?',(entry_id,owner)).fetchone(): return row
    raise HTTPException(404,'Arquivo não encontrado.')

@router.get('/api/files/{entry_id}/content')
def content(entry_id: str, request: Request, version: str | None=None, session=Depends(full)):
    service=svc(request)
    with service.db.connect() as c:
        row=readable(c,entry_id,session['user_id'])
        if version is not None and row['owner']!=session['user_id']:
            raise HTTPException(403,'O histórico é privado do proprietário.')
        v=c.execute('SELECT * FROM versions WHERE entry_id=? AND id=?',(entry_id,version)).fetchone() if version else latest(c,entry_id)
        if not v or row['kind']!='file': raise HTTPException(404,'Revisão não encontrada.')
    path=service.settings.data_dir/'blobs'/v['id']
    if not path.is_file(): raise HTTPException(503,'Arquivo indisponível. Verifique a restauração do volume.')
    return FileResponse(path,media_type='application/octet-stream',headers={
        'Content-Disposition':"attachment; filename*=UTF-8''"+quote(row['name'],safe=''),
        'ETag':'"'+v['id']+'"','X-Content-SHA256':v['sha256'],
        'Content-Security-Policy':"sandbox; default-src 'none'"})

@router.get('/api/files/{entry_id}/versions')
def versions(entry_id: str, request: Request, session=Depends(full)):
    with svc(request).db.connect() as c:
        row=readable(c,entry_id,session['user_id'])
        if row['owner']!=session['user_id']:raise HTTPException(403,'O histórico é privado do proprietário.')
        rows=c.execute('SELECT id,size,sha256,created,sequence FROM versions WHERE entry_id=? ORDER BY sequence DESC',(entry_id,)).fetchall()
    return {'versions':[dict(r) for r in rows]}

def descendants(c, entry_id):
    return [r[0] for r in c.execute('''WITH RECURSIVE tree(id) AS (SELECT id FROM entries WHERE id=? UNION ALL
        SELECT e.id FROM entries e JOIN tree t ON e.parent=t.id) SELECT id FROM tree''',(entry_id,))]

@router.patch('/api/files/{entry_id}')
def patch_entry(entry_id: str, body: EntryPatch, request: Request, session=Depends(full)):
    try:
        with svc(request).db.transaction() as c:
            authorize(c,session)
            row=owned(c,entry_id,session['user_id']);name=body.name if body.name is not None else row['name']
            parent=body.parent if 'parent' in body.model_fields_set else row['parent']
            parent_folder(c,parent,session['user_id'])
            if parent in descendants(c,entry_id): raise HTTPException(409,'Uma pasta não pode ser movida para dentro dela mesma.')
            c.execute('UPDATE entries SET name=?,parent=?,updated=? WHERE id=?',(name,parent,now(),entry_id))
            return present(c,owned(c,entry_id,session['user_id']))
    except sqlite3.IntegrityError: raise HTTPException(409,'Já existe um item com esse nome no destino.')

@router.delete('/api/files/{entry_id}')
def trash(entry_id: str, request: Request, session=Depends(full)):
    service=svc(request)
    with service.db.transaction() as c:
        authorize(c,session)
        owned(c,entry_id,session['user_id'])
        for item in descendants(c,entry_id): c.execute('UPDATE entries SET trash=?,updated=? WHERE id=? AND trash IS NULL',(entry_id,now(),item))
        service.audit(c,session['user_id'],'file.trash',entry_id)
    return {'ok':True}

@router.post('/api/files/{entry_id}/restore')
def restore(entry_id: str, request: Request, session=Depends(full)):
    try:
        with svc(request).db.transaction() as c:
            authorize(c,session)
            row=owned(c,entry_id,session['user_id'],live=False)
            if row['trash']!=entry_id: raise HTTPException(409,'Restaure primeiro a pasta que contém este item.')
            if row['parent'] and owned(c,row['parent'],session['user_id'],live=False)['trash']:
                c.execute('UPDATE entries SET parent=NULL WHERE id=?',(entry_id,))
            c.execute('UPDATE entries SET trash=NULL,updated=? WHERE trash=?',(now(),entry_id))
    except sqlite3.IntegrityError: raise HTTPException(409,'Há um item com o mesmo nome no destino. Renomeie-o antes de restaurar.')
    return {'ok':True}

@router.delete('/api/files/{entry_id}/purge')
def purge(entry_id: str, request: Request, session=Depends(full)):
    service=svc(request);blobs=[]
    with service.db.transaction() as c:
        authorize(c,session)
        row=owned(c,entry_id,session['user_id'],live=False)
        if not row['trash']: raise HTTPException(409,'Envie o item para a lixeira antes de excluir definitivamente.')
        for item in reversed(descendants(c,entry_id)):
            blobs.extend(r[0] for r in c.execute('SELECT id FROM versions WHERE entry_id=?',(item,)))
            c.execute('DELETE FROM entries WHERE id=?',(item,))
        service.audit(c,session['user_id'],'file.purge',entry_id)
    for blob in blobs: (service.settings.data_dir/'blobs'/blob).unlink(missing_ok=True)
    return {'ok':True}

@router.get('/api/files/{entry_id}/shares')
def shares(entry_id: str, request: Request, session=Depends(full)):
    with svc(request).db.connect() as c:
        owned(c,entry_id,session['user_id'])
        rows=c.execute('SELECT u.id,u.username,u.name FROM shares s JOIN users u ON s.recipient=u.id WHERE s.entry_id=? ORDER BY u.username',(entry_id,)).fetchall()
    return {'shares':[dict(r) for r in rows]}

@router.post('/api/files/{entry_id}/shares')
def share(entry_id: str, body: Share, request: Request, session=Depends(full)):
    with svc(request).db.transaction() as c:
        authorize(c,session)
        if owned(c,entry_id,session['user_id'])['kind']!='file': raise HTTPException(422,'Compartilhe arquivos individuais nesta versão.')
        recipient=c.execute('SELECT id FROM users WHERE username=? AND enabled=1',(body.username.strip(),)).fetchone()
        if not recipient or recipient['id']==session['user_id']: raise HTTPException(404,'Destinatário não encontrado.')
        c.execute('INSERT OR IGNORE INTO shares VALUES(?,?,?)',(entry_id,recipient['id'],now()))
    return {'ok':True}

@router.delete('/api/files/{entry_id}/shares/{recipient}')
def unshare(entry_id: str, recipient: str, request: Request, session=Depends(full)):
    with svc(request).db.transaction() as c:
        authorize(c,session)
        owned(c,entry_id,session['user_id']);c.execute('DELETE FROM shares WHERE entry_id=? AND recipient=?',(entry_id,recipient))
    return {'ok':True}

@router.delete('/api/files/{entry_id}/versions/{version_id}')
def delete_version(entry_id: str,version_id: str,request: Request,session=Depends(full)):
    service=svc(request)
    with service.db.transaction() as c:
        authorize(c,session);owned(c,entry_id,session['user_id'])
        version=c.execute('SELECT * FROM versions WHERE entry_id=? AND id=?',(entry_id,version_id)).fetchone()
        if not version:raise HTTPException(404,'Revisão não encontrada.')
        if latest(c,entry_id)['id']==version_id:raise HTTPException(409,'A revisão atual não pode ser excluída isoladamente.')
        c.execute('DELETE FROM versions WHERE id=?',(version_id,))
        service.audit(c,session['user_id'],'version.delete',entry_id)
    (service.settings.data_dir/'blobs'/version_id).unlink(missing_ok=True)
    return {'ok':True}

@router.post('/api/files/{entry_id}/versions/{version_id}/restore')
def restore_version(entry_id: str,version_id: str,request: Request,session=Depends(full)):
    service=svc(request);expected=request.headers.get('if-match')
    if not expected:raise HTTPException(428,'If-Match é obrigatório para restaurar conteúdo.')
    with service.db.connect() as c:
        owned(c,entry_id,session['user_id']);current=latest(c,entry_id)
        if expected!='"'+current['id']+'"':raise HTTPException(412,'O arquivo mudou. Atualize antes de restaurar.')
        old=c.execute('SELECT * FROM versions WHERE entry_id=? AND id=?',(entry_id,version_id)).fetchone()
        if not old:raise HTTPException(404,'Revisão não encontrada.')
    reservation=reserve(service,session,old['size'])
    temp=service.settings.data_dir/'tmp'/reservation;blob=service.settings.data_dir/'blobs'/reservation;published=False
    try:
        try:shutil.copyfile(service.settings.data_dir/'blobs'/version_id,temp)
        except FileNotFoundError:raise HTTPException(409,'A revisão foi removida durante a restauração.')
        with temp.open('rb') as durable:os.fsync(durable.fileno())
        with service.db.transaction() as c:
            authorize(c,session);owned(c,entry_id,session['user_id']);current=latest(c,entry_id)
            if expected!='"'+current['id']+'"':raise HTTPException(412,'Outra revisão foi salva durante a restauração.')
            user=c.execute('SELECT quota FROM users WHERE id=?',(session['user_id'],)).fetchone()
            used,pending=usage(c,session['user_id'])
            if used+pending>user['quota']:raise HTTPException(413,'A cota foi alterada durante a restauração.')
            temp.replace(blob)
            directory=os.open(blob.parent,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(directory)
            finally:os.close(directory)
            c.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?)',(reservation,entry_id,session['user_id'],old['size'],old['sha256'],now(),current['sequence']+1))
            c.execute('UPDATE entries SET updated=? WHERE id=?',(now(),entry_id))
            c.execute('DELETE FROM reservations WHERE id=?',(reservation,))
            service.audit(c,session['user_id'],'version.restore',entry_id)
            result=present(c,owned(c,entry_id,session['user_id']))
        published=True;return result
    finally:
        temp.unlink(missing_ok=True)
        if not published:blob.unlink(missing_ok=True)
        with service.db.transaction() as c:c.execute('DELETE FROM reservations WHERE id=?',(reservation,))
