"""SOS Patinhas — aplicação acadêmica web, FastAPI, Jinja2 e SQLite.
Instalação: pip install -r requirements.txt; python app.py.
"""
import argparse
import csv
import hashlib
import io
import json
import os
import re
import secrets
import smtplib
from email.message import EmailMessage
import sqlite3
import uuid
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from argon2 import PasswordHasher, exceptions as argon_exc
from fastapi import FastAPI, HTTPException, Request
from starlette.datastructures import UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image, UnidentifiedImageError
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas
from starlette.middleware.sessions import SessionMiddleware

ROOT = Path(__file__).resolve().parent
DB = Path(os.getenv('SOS_DB', str(ROOT / 'sos_patinhas.db')))
UPLOADS = ROOT / 'static' / 'uploads'
PRIVATE = ROOT / 'private'
UPLOADS.mkdir(parents=True, exist_ok=True)
PRIVATE.mkdir(parents=True, exist_ok=True)
SECRET = os.environ.get('SOS_SECRET_KEY') or secrets.token_hex(32)
if not os.getenv('SOS_SECRET_KEY'):
    print('[AVISO] SOS_SECRET_KEY não configurada. Sessões serão invalidadas ao reiniciar. Configure para utilização contínua.')
app = FastAPI(title='SOS Patinhas', docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=SECRET, same_site='lax', https_only=os.getenv('SOS_SECURE_COOKIES') == '1', max_age=3600*12)
app.mount('/static', StaticFiles(directory=str(ROOT / 'static')), name='static')
@app.middleware('http')
async def add_security_headers(request:Request, call_next):
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['Permissions-Policy']='geolocation=(), camera=(), microphone=()'
    if request.url.path.startswith(('/painel','/minha-conta','/redefinir')):
        response.headers['Cache-Control']='no-store'
    if os.getenv('SOS_SECURE_COOKIES')=='1':
        response.headers['Strict-Transport-Security']='max-age=31536000'
    return response

env = Environment(loader=FileSystemLoader(str(ROOT / 'templates')), autoescape=select_autoescape(['html', 'xml']))
ph = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=2)
ANIMAL_STATES = ['Em tratamento','Em quarentena','Apto para adoção','Em processo de adoção','Adotado','Fugiu','Óbito']
DENUNCIA_STATES = ['Recebida','Em verificação','Resgate agendado','Resgate realizado','Não procedente']

@contextmanager
def db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=15000')
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, cpf TEXT UNIQUE, phone TEXT, dob TEXT, cep TEXT, street TEXT, number TEXT, district TEXT, city TEXT, uf TEXT, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'adotante', position TEXT, active INTEGER NOT NULL DEFAULT 1, restricted_reason TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rescues(id INTEGER PRIMARY KEY, protocol TEXT NOT NULL UNIQUE, provisional_name TEXT NOT NULL, species TEXT NOT NULL, sex TEXT NOT NULL, size TEXT NOT NULL, rescue_date TEXT NOT NULL, location TEXT NOT NULL, initial_health TEXT NOT NULL, behavior TEXT, created_by INTEGER NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(created_by) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS animals(id INTEGER PRIMARY KEY, rescue_id INTEGER UNIQUE, name TEXT NOT NULL, species TEXT NOT NULL, breed TEXT NOT NULL, age TEXT NOT NULL, sex TEXT NOT NULL, size TEXT NOT NULL, description TEXT, health TEXT NOT NULL, neutered INTEGER NOT NULL DEFAULT 0, vaccinated INTEGER NOT NULL DEFAULT 0, dewormed INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, photo TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(rescue_id) REFERENCES rescues(id));
CREATE TABLE IF NOT EXISTS animal_changes(id INTEGER PRIMARY KEY, animal_id INTEGER NOT NULL, actor_id INTEGER, old_status TEXT, new_status TEXT, reason TEXT, changed_at TEXT, FOREIGN KEY(animal_id) REFERENCES animals(id));
CREATE TABLE IF NOT EXISTS complaints(id INTEGER PRIMARY KEY, protocol TEXT NOT NULL UNIQUE, species TEXT NOT NULL, occurred_at TEXT NOT NULL, location TEXT NOT NULL, reference TEXT, description TEXT NOT NULL, anonymous INTEGER NOT NULL DEFAULT 0, reporter_id INTEGER, status TEXT NOT NULL DEFAULT 'Recebida', evidence TEXT, created_at TEXT NOT NULL, FOREIGN KEY(reporter_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS adoptions(id INTEGER PRIMARY KEY, animal_id INTEGER NOT NULL, user_id INTEGER NOT NULL, household TEXT NOT NULL, experience TEXT NOT NULL, motivation TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Em análise', in_review INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, reviewed_at TEXT, review_reason TEXT, signed_term TEXT, finalized_at TEXT, FOREIGN KEY(animal_id) REFERENCES animals(id), FOREIGN KEY(user_id) REFERENCES users(id), UNIQUE(animal_id,user_id));
CREATE TABLE IF NOT EXISTS followups(id INTEGER PRIMARY KEY, adoption_id INTEGER NOT NULL, due_date TEXT NOT NULL, contacted_at TEXT, channel TEXT, notes TEXT, photo TEXT, FOREIGN KEY(adoption_id) REFERENCES adoptions(id));
CREATE TABLE IF NOT EXISTS intakes(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,species TEXT NOT NULL,age TEXT,location TEXT NOT NULL,condition TEXT NOT NULL,reason TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'Recebido',created_at TEXT NOT NULL,FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS donations(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, amount REAL, item TEXT, quantity INTEGER, condition TEXT, donor TEXT, method TEXT, received_at TEXT NOT NULL, recorded_by INTEGER NOT NULL, FOREIGN KEY(recorded_by) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS volunteers(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL UNIQUE, area TEXT NOT NULL, availability TEXT NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Pendente', created_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS campaigns(id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL, type TEXT NOT NULL, event_date TEXT, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, read_at TEXT, created_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, actor_id INTEGER, action TEXT NOT NULL, details TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts(id INTEGER PRIMARY KEY, identifier TEXT NOT NULL, attempted_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS password_resets(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,token_hash TEXT NOT NULL UNIQUE,requested_at TEXT NOT NULL,used_at TEXT,FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS privacy_requests(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,request_type TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'Pendente',created_at TEXT NOT NULL,resolved_at TEXT,FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS animal_photos(id INTEGER PRIMARY KEY, animal_id INTEGER NOT NULL, photo TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(animal_id) REFERENCES animals(id));
CREATE TABLE IF NOT EXISTS animal_edits(id INTEGER PRIMARY KEY, animal_id INTEGER NOT NULL, actor_id INTEGER, details TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(animal_id) REFERENCES animals(id));
CREATE TABLE IF NOT EXISTS partners(id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, description TEXT, website TEXT, contact TEXT, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS volunteer_tasks(id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL, when_at TEXT, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_animals_status ON animals(status);
CREATE INDEX IF NOT EXISTS idx_adoptions_animal ON adoptions(animal_id,status,created_at);
CREATE INDEX IF NOT EXISTS idx_complaints_status ON complaints(status);
CREATE INDEX IF NOT EXISTS idx_followups_due ON followups(due_date);
'''

def now(): return datetime.now().isoformat(timespec='seconds')
def today(): return datetime.now().strftime('%Y-%m-%d')
def clean(v, limit=300): return str(v or '').strip()[:limit]
def digits(v): return re.sub(r'\D', '', str(v or ''))
def rowdict(r): return dict(r) if r else None

def bootstrap():
    with db() as c:
        c.executescript(SCHEMA)
        additions={'rescues': [('photo','TEXT')], 'animals': [('vaccination_due','TEXT')],
                   'adoptions':[('evaluation_notes','TEXT'),('evaluation_file','TEXT')],
                   'notifications':[('event_key','TEXT')]}
        for table, cols in additions.items():
            existing={row['name'] for row in c.execute(f'PRAGMA table_info({table})')}
            for name, kind in cols:
                if name not in existing:
                    c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {kind}')
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_event ON notifications(event_key)')
        # Somente converter referências conhecidas dos quatro animais de demonstração antigos.
        old={'dog-mel.svg':'dog-mel-photo.webp','cat-bidu.svg':'cat-bidu-photo.webp',
             'dog-luna.svg':'dog-luna-photo.webp','dog-thor.svg':'dog-thor-photo.webp'}
        for oldname, newname in old.items():
            c.execute('UPDATE animals SET photo=? WHERE photo=?',('/static/img/'+newname,'/static/img/'+oldname))
        if c.execute('SELECT COUNT(*) FROM campaigns').fetchone()[0] == 0:
            c.executemany('INSERT INTO campaigns(title,description,type,event_date,created_at) VALUES(?,?,?,?,?)', [
                ('Um lar muda tudo', 'Conheça os animais disponíveis e descubra como fazer uma adoção responsável.', 'Adoção', None, now()),
                ('Doe cuidado, espalhe amor', 'Ração, cobertores, produtos de higiene e tempo voluntário fazem a diferença.', 'Solidariedade', None, now()),
                ('Proteção começa com informação', 'Aprenda a identificar sinais de abandono e maus-tratos e como denunciar.', 'Conscientização', None, now())])


def current_user(request):
    uid = request.session.get('uid')
    if not uid: return None
    with db() as c:
        u = c.execute('SELECT * FROM users WHERE id=? AND active=1', (uid,)).fetchone()
    return rowdict(u)

def page(request, name, status=200, **kwargs):
    if not request.session.get('csrf'):
        request.session['csrf'] = secrets.token_urlsafe(32)
    user = current_user(request)
    flash = request.session.pop('flash', None)
    tpl = env.get_template(name)
    html = tpl.render(request=request, user=user, csrf=request.session['csrf'], flash=flash, now=now(), today=today(), **kwargs)
    return HTMLResponse(html, status_code=status)

def go(url, request=None, msg=None, error=False):
    if request is not None and msg:
        request.session['flash'] = {'text': msg, 'error': error}
    return RedirectResponse(url, status_code=303)

def secure_form(request, form):
    expected = request.session.get('csrf')
    got = str(form.get('csrf') or '')
    if not expected or not secrets.compare_digest(got, expected):
        raise HTTPException(status_code=403, detail='Formulário expirado. Atualize a página e tente novamente.')

def require_user(request, admin=False):
    u = current_user(request)
    if not u: raise HTTPException(401, detail='Faça login para continuar.')
    if admin and u['role'] not in ('funcionario','admin'): raise HTTPException(403, detail='Acesso reservado à equipe da ONG.')
    return u

def audit(c, uid, action, details=''):
    c.execute('INSERT INTO audit(actor_id,action,details,created_at) VALUES(?,?,?,?)', (uid, action, clean(details,500), now()))

def notify(c, uid, title, body, event_key=None):
    c.execute('INSERT OR IGNORE INTO notifications(user_id,title,body,created_at,event_key) VALUES(?,?,?,?,?)',
              (uid,title,body,now(),event_key))

def scheduled_alerts(c):
    """Create idempotent internal alerts when the administrative panel is consulted.
    This is not a background email/SMS service.
    """
    until=(datetime.now()+timedelta(days=7)).strftime('%Y-%m-%d')
    staff=[r['id'] for r in c.execute("SELECT id FROM users WHERE role IN ('admin','funcionario') AND active=1")]
    for r in c.execute('SELECT f.id,f.due_date,n.name FROM followups f JOIN adoptions a ON a.id=f.adoption_id JOIN animals n ON n.id=a.animal_id WHERE f.contacted_at IS NULL AND f.due_date<=?',(until,)):
        for uid in staff:notify(c,uid,'Acompanhamento pendente',f'{r["name"]}: agendado para {r["due_date"]}.',f'followup:{r["id"]}:{r["due_date"]}:{uid}')
    for r in c.execute("SELECT id,name,vaccination_due FROM animals WHERE vaccination_due IS NOT NULL AND vaccination_due!='' AND vaccination_due<=? AND status NOT IN ('Óbito','Fugiu')",(until,)):
        for uid in staff:notify(c,uid,'Vacinação próxima',f'{r["name"]}: previsão para {r["vaccination_due"]}.',f'vaccine:{r["id"]}:{r["vaccination_due"]}:{uid}')

def validate_cpf(cpf):
    cpf = digits(cpf)
    if len(cpf) != 11 or len(set(cpf)) == 1: return False
    for end in (9,10):
        check=(sum(int(cpf[i])*(end+1-i) for i in range(end))*10)%11
        if check == 10: check=0
        if int(cpf[end]) != check: return False
    return True

async def upload_image(file):
    if not isinstance(file, UploadFile) or not file.filename: return None
    b = await file.read(4*1024*1024+1)
    if len(b)>4*1024*1024: raise ValueError('Imagem muito grande (limite de 4 MB).')
    try:
        im = Image.open(io.BytesIO(b)); im.verify()
        im = Image.open(io.BytesIO(b))
        if im.format not in ('JPEG','PNG','WEBP'): raise ValueError('Use imagens JPG, PNG ou WEBP.')
        if im.width*im.height > 18_000_000: raise ValueError('Imagem com resolução muito grande.')
        im.thumbnail((1280,1280))
        im = im.convert('RGB')
        filename = uuid.uuid4().hex + '.webp'
        im.save(UPLOADS / filename, 'WEBP', quality=84, method=4)
        return '/static/uploads/'+filename
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError('Arquivo de imagem inválido.') from e

async def upload_private(file, accept='evidence'):
    if not isinstance(file, UploadFile) or not file.filename: return None
    data=await file.read(6*1024*1024+1)
    if len(data)>6*1024*1024: raise ValueError('Arquivo muito grande (até 6 MB).')
    if accept=='pdf':
        if not data.startswith(b'%PDF-'): raise ValueError('Envie o termo assinado em formato PDF.')
        suffix='.pdf'
    else:
        if data.startswith(b'%PDF-'): suffix='.pdf'
        else:
            try:
                img=Image.open(io.BytesIO(data));img.verify()
                if img.format not in ('JPEG','PNG','WEBP'):raise ValueError('Envie imagem JPG/PNG/WEBP ou PDF.')
                suffix={ 'JPEG': '.jpg', 'PNG': '.png','WEBP':'.webp'}[img.format]
            except (UnidentifiedImageError, OSError): raise ValueError('Envie imagem JPG/PNG/WEBP ou PDF.')
    fn=uuid.uuid4().hex+suffix
    (PRIVATE/fn).write_bytes(data)
    return fn

@app.exception_handler(HTTPException)
async def problem(req, exc):
    if exc.status_code==401: return go('/entrar?proximo='+quote(req.url.path))
    return page(req,'message.html',status=exc.status_code, heading=f'Erro {exc.status_code}', message=exc.detail)

@app.get('/')
def home(req:Request):
    with db() as c:
        animals=[dict(x) for x in c.execute("SELECT * FROM animals WHERE status='Apto para adoção' ORDER BY id DESC LIMIT 4")]
        campaigns=[dict(x) for x in c.execute('SELECT * FROM campaigns WHERE active=1 ORDER BY id DESC LIMIT 3')]
        stats=dict(available=c.execute("SELECT COUNT(*) FROM animals WHERE status='Apto para adoção'").fetchone()[0], adopted=c.execute("SELECT COUNT(*) FROM animals WHERE status='Adotado'").fetchone()[0])
    return page(req,'home.html',animals=animals,campaigns=campaigns,stats=stats)

@app.get('/adotar')
def catalog(req:Request, especie:str='', porte:str='', busca:str=''):
    sql="SELECT * FROM animals WHERE status='Apto para adoção'"
    values=[]
    if especie in ('Cão','Gato','Outro'): sql+=' AND species=?';values.append(especie)
    if porte in ('Pequeno','Médio','Grande'): sql+=' AND size=?';values.append(porte)
    if busca: sql+=' AND (name LIKE ? OR breed LIKE ? OR description LIKE ?)';values += ['%'+busca[:60]+'%']*3
    sql+=' ORDER BY id DESC'
    with db() as c: animals=[dict(x) for x in c.execute(sql,values)]
    return page(req,'catalog.html',animals=animals,especie=especie,porte=porte,busca=busca)

@app.get('/animal/{animal_id}')
def animal_page(req:Request, animal_id:int):
    with db() as c: animal=rowdict(c.execute("SELECT * FROM animals WHERE id=? AND status='Apto para adoção'", (animal_id,)).fetchone())
    if not animal: raise HTTPException(404, 'Animal não encontrado ou não disponível.')
    with db() as c:gallery=[dict(x) for x in c.execute('SELECT * FROM animal_photos WHERE animal_id=? ORDER BY id',(animal_id,))]
    return page(req,'animal.html',animal=animal,gallery=gallery)

@app.get('/sobre')
def about(req:Request):return page(req,'about.html',kind='sobre')
@app.get('/conteudos')
def learn(req:Request):return page(req,'about.html',kind='conteudos')
@app.get('/privacidade')
def privacy(req:Request):return page(req,'about.html',kind='privacidade')
@app.get('/termos')
def terms(req:Request):return page(req,'about.html',kind='termos')

@app.get('/parceiros')
def partners_page(req:Request):
    with db() as c:rows=[dict(x) for x in c.execute('SELECT * FROM partners WHERE active=1 ORDER BY name')]
    return page(req,'partners.html',rows=rows)

@app.get('/painel/parceiros')
def partners_admin(req:Request):
    require_user(req,True)
    with db() as c:rows=[dict(x) for x in c.execute('SELECT * FROM partners ORDER BY id DESC')]
    return page(req,'partners_admin.html',rows=rows,active='parceiros')

@app.post('/painel/parceiros')
async def partner_create(req:Request):
    actor=require_user(req,True);f=await req.form();secure_form(req,f)
    name=clean(f.get('name'),140);category=clean(f.get('category'),80);description=clean(f.get('description'),500)
    website=clean(f.get('website'),250);contact=clean(f.get('contact'),180)
    if len(name)<3 or not category or len(description)<10:return go('/painel/parceiros',req,'Informe nome, categoria e descrição.',True)
    if website and not re.fullmatch(r'https://[^\s]+',website):return go('/painel/parceiros',req,'Use um endereço HTTPS para o site.',True)
    with db() as c:
        c.execute('INSERT INTO partners(name,category,description,website,contact,created_at) VALUES(?,?,?,?,?,?)',(name,category,description,website,contact,now()))
        audit(c,actor['id'],'parceiro_criado',name)
    return go('/painel/parceiros',req,'Parceiro cadastrado.')

@app.post('/painel/parceiros/{pid}/alternar')
async def partner_toggle(req:Request,pid:int):
    actor=require_user(req,True);f=await req.form();secure_form(req,f)
    with db() as c:
        c.execute('UPDATE partners SET active=1-active WHERE id=?',(pid,))
        audit(c,actor['id'],'parceiro_visibilidade',f'ID {pid}')
    return go('/painel/parceiros',req,'Visibilidade atualizada.')

@app.get('/entrar')
def login_page(req:Request, proximo:str=''):
    return page(req,'auth.html',mode='login',proximo=proximo)

@app.post('/entrar')
async def login(req:Request):
    f=await req.form(); secure_form(req,f)
    ident=clean(f.get('ident'),160).lower(); pwd=str(f.get('password') or '')
    cutoff=(datetime.now()-timedelta(minutes=15)).isoformat(timespec='seconds')
    with db() as c:
        attempts=c.execute('SELECT COUNT(*) FROM login_attempts WHERE identifier=? AND attempted_at>?',(hashlib.sha256(ident.encode()).hexdigest(),cutoff)).fetchone()[0]
        if attempts>=3: return go('/entrar',req,'Acesso temporariamente bloqueado. Tente novamente em 15 minutos.',True)
        u=c.execute('SELECT * FROM users WHERE lower(email)=? OR cpf=?',(ident,digits(ident))).fetchone()
        valid=False
        if u and u['active']:
            try: valid=ph.verify(u['password_hash'],pwd)
            except (argon_exc.VerifyMismatchError,argon_exc.InvalidHashError,argon_exc.VerificationError): pass
        if not valid:
            c.execute('INSERT INTO login_attempts(identifier,attempted_at) VALUES(?,?)',(hashlib.sha256(ident.encode()).hexdigest(),now()))
            return go('/entrar',req,'E-mail/CPF ou senha incorretos.',True)
        c.execute('DELETE FROM login_attempts WHERE identifier=?',(hashlib.sha256(ident.encode()).hexdigest(),))
        audit(c,u['id'],'login')
    req.session.clear();req.session['uid']=u['id'];req.session['csrf']=secrets.token_urlsafe(32)
    return go('/painel' if u['role'] in ('funcionario','admin') else '/minha-conta',req,'Bem-vindo(a) de volta!')

@app.get('/cadastro')
def signup_page(req:Request):return page(req,'auth.html',mode='register',proximo='')

@app.post('/cadastro')
async def signup(req:Request):
    f=await req.form();secure_form(req,f)
    name=clean(f.get('name'),140);email=clean(f.get('email'),160).lower();cpf=digits(f.get('cpf'));phone=digits(f.get('phone'));dob=clean(f.get('dob'),10)
    pwd=str(f.get('password') or '');confirm=str(f.get('confirm') or '')
    if len(name)<4 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email) or not validate_cpf(cpf) or len(phone)<10 or len(pwd)<10 or pwd!=confirm or f.get('agree')!='sim':
        return go('/cadastro',req,'Confira nome, e-mail, CPF, telefone, senha (mínimo 10 caracteres) e aceite os termos.',True)
    try:
        d=datetime.strptime(dob,'%Y-%m-%d')
        if (datetime.now()-d).days<18*365:raise ValueError()
    except ValueError: return go('/cadastro',req,'Informe uma data de nascimento válida. Cadastro destinado a maiores de 18 anos.',True)
    fields=[clean(f.get(x),120) for x in ('cep','street','number','district','city','uf')]
    if not all(fields) or len(digits(fields[0]))!=8: return go('/cadastro',req,'Preencha o endereço completo e um CEP válido.',True)
    try:
        with db() as c:
            c.execute('INSERT INTO users(name,email,cpf,phone,dob,cep,street,number,district,city,uf,password_hash,role,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (name,email,cpf,phone,dob,*fields,ph.hash(pwd),'adotante',now()))
            uid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            audit(c,uid,'cadastro_usuario')
    except sqlite3.IntegrityError: return go('/cadastro',req,'CPF ou e-mail já cadastrado.',True)
    req.session.clear();req.session['uid']=uid;req.session['csrf']=secrets.token_urlsafe(32)
    return go('/minha-conta',req,'Cadastro realizado! Agora você pode solicitar uma adoção.')

@app.post('/sair')
async def logout(req:Request):
    f=await req.form();secure_form(req,f)
    req.session.clear()
    return go('/',req,'Você saiu da sua conta.')

@app.get('/minha-conta')
def account(req:Request):
    u=require_user(req)
    with db() as c:
        applications=[dict(x) for x in c.execute('SELECT a.*,n.name animal_name, n.photo FROM adoptions a JOIN animals n ON n.id=a.animal_id WHERE a.user_id=? ORDER BY a.id DESC',(u['id'],))]
        notes=[dict(x) for x in c.execute('SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 20',(u['id'],))]
        volunteering=rowdict(c.execute('SELECT * FROM volunteers WHERE user_id=?',(u['id'],)).fetchone())
    return page(req,'account.html',applications=applications,notes=notes,volunteering=volunteering)

@app.post('/minha-conta/senha')
async def password_change(req:Request):
    u=require_user(req);f=await req.form();secure_form(req,f)
    try: valid=ph.verify(u['password_hash'],str(f.get('current') or ''))
    except (argon_exc.VerifyMismatchError,argon_exc.VerificationError,argon_exc.InvalidHashError):valid=False
    new=str(f.get('new') or '')
    if not valid or len(new)<10 or new!=f.get('confirm'): return go('/minha-conta',req,'Senha atual incorreta ou nova senha inválida (mínimo 10 caracteres).',True)
    with db() as c:
        c.execute('UPDATE users SET password_hash=? WHERE id=?',(ph.hash(new),u['id']))
        audit(c,u['id'],'troca_senha')
    return go('/minha-conta',req,'Senha alterada com sucesso.')

@app.get('/adotar/{animal_id}/solicitar')
def apply_page(req:Request,animal_id:int):
    u=require_user(req)
    with db() as c: a=rowdict(c.execute("SELECT * FROM animals WHERE id=? AND status='Apto para adoção'",(animal_id,)).fetchone())
    if not a:raise HTTPException(404,'Animal indisponível para novas solicitações.')
    return page(req,'apply.html',animal=a)

@app.post('/adotar/{animal_id}/solicitar')
async def apply(req:Request,animal_id:int):
    u=require_user(req);f=await req.form();secure_form(req,f)
    if u['restricted_reason']:return go('/minha-conta',req,'Seu cadastro exige análise prévia pela equipe.',True)
    household=clean(f.get('household'),500);experience=clean(f.get('experience'),600);motivation=clean(f.get('motivation'),1200)
    if min(len(household),len(experience),len(motivation))<10: return go(f'/adotar/{animal_id}/solicitar',req,'Responda às três perguntas com pelo menos 10 caracteres.',True)
    with db() as c:
        animal=c.execute('SELECT status,name FROM animals WHERE id=?',(animal_id,)).fetchone()
        if not animal or animal['status']!='Apto para adoção':return go('/adotar',req,'Este animal já está em processo de adoção.',True)
        try:
            c.execute('INSERT INTO adoptions(animal_id,user_id,household,experience,motivation,created_at) VALUES(?,?,?,?,?,?)',(animal_id,u['id'],household,experience,motivation,now()))
        except sqlite3.IntegrityError:return go('/minha-conta',req,'Você já realizou uma solicitação para este animal.',True)
        audit(c,u['id'],'solicitacao_adocao',f'animal {animal_id}')
    return go('/minha-conta',req,'Solicitação registrada! A ONG analisará os interessados pela ordem de chegada.')

@app.post('/minha-conta/solicitacoes/{adoption_id}/desistir')
async def withdraw_adoption(req:Request,adoption_id:int):
    u=require_user(req);f=await req.form();secure_form(req,f)
    with db() as c:
        a=c.execute('SELECT * FROM adoptions WHERE id=? AND user_id=?',(adoption_id,u['id'])).fetchone()
        if not a:raise HTTPException(404,'Solicitação não encontrada.')
        if a['status']!='Em análise':return go('/minha-conta',req,'Só é possível desistir antes da aprovação.',True)
        c.execute("UPDATE adoptions SET status='Desistiu',in_review=0,reviewed_at=? WHERE id=?",(now(),adoption_id))
        if a['in_review']:
            c.execute("UPDATE animals SET status='Apto para adoção',updated_at=? WHERE id=? AND status='Em processo de adoção'",(now(),a['animal_id']))
            next_row=c.execute("SELECT user_id FROM adoptions WHERE animal_id=? AND status='Em análise' ORDER BY created_at,id LIMIT 1",(a['animal_id'],)).fetchone()
            if next_row:notify(c,next_row['user_id'],'Próximo na fila','Sua solicitação é a próxima a ser avaliada.')
        audit(c,u['id'],'desistencia_adocao',f'Solicitação {adoption_id}')
    return go('/minha-conta',req,'Desistência registrada. O próximo da fila poderá ser avaliado.')

@app.get('/denunciar')
def complaint_page(req:Request):return page(req,'complaint.html')

@app.post('/denunciar')
async def complaint(req:Request):
    f=await req.form();secure_form(req,f)
    u=current_user(req);spec=clean(f.get('species'),45);when=clean(f.get('occurred_at'),35);loc=clean(f.get('location'),300);ref=clean(f.get('reference'),200);description=clean(f.get('description'),2500)
    anonymous=1 if f.get('anonymous')=='sim' else 0
    if spec not in ('Cão','Gato','Outro','Não sei') or not when or len(loc)<7 or len(description)<20:
        return go('/denunciar',req,'Preencha espécie, data, local e descrição (mínimo de 20 caracteres).',True)
    if len(when)<10: return go('/denunciar',req,'Informe uma data válida.',True)
    try:
        filename=await upload_private(f.get('evidence'))
    except ValueError as e: return go('/denunciar',req,str(e),True)
    protocol='DEN-'+datetime.now().strftime('%Y%m%d')+'-'+secrets.token_hex(3).upper()
    with db() as c:
        c.execute('INSERT INTO complaints(protocol,species,occurred_at,location,reference,description,anonymous,reporter_id,evidence,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
         (protocol,spec,when,loc,ref,description,anonymous,None if anonymous else u['id'] if u else None,filename,now()))
        audit(c,None if anonymous else u['id'] if u else None,'denuncia_criada',protocol)
    return page(req,'message.html',heading='Denúncia registrada',message='Sua denúncia foi recebida. Guarde o protocolo para referência: '+protocol+'. Em risco imediato, procure também os órgãos públicos competentes.')

def pix_field(tag,value):
    raw=str(value).encode('ascii')
    if len(raw)>99:raise ValueError('Campo Pix muito longo')
    return tag+f'{len(raw):02d}'+str(value)

def pix_static_code(key,name,city):
    """BR Code estático sem valor definido; sem intermediação financeira.
    A organização deve validar o QR resultante em um aplicativo bancário antes da publicação.
    """
    key=key.strip()
    if not 1<=len(key.encode('utf-8'))<=77:raise ValueError('Chave Pix inválida')
    def norm(x,length):
        value=unicodedata.normalize('NFKD',x).encode('ascii','ignore').decode('ascii').upper()
        value=re.sub(r'[^A-Z0-9 ]','',value).strip()[:length]
        if not value:raise ValueError('Nome e cidade oficiais obrigatórios')
        return value
    name=norm(name,25);city=norm(city,15)
    data=pix_field('00','01')+pix_field('26',pix_field('00','br.gov.bcb.pix')+pix_field('01',key))
    data+=pix_field('52','0000')+pix_field('53','986')+pix_field('58','BR')
    data+=pix_field('59',name)+pix_field('60',city)+pix_field('62',pix_field('05','***'))+'6304'
    crc=0xffff
    for b in data.encode('utf-8'):
        crc ^= b<<8
        for _ in range(8):crc=((crc<<1)^0x1021 if crc&0x8000 else crc<<1)&0xffff
    return data+f'{crc:04X}'

@app.get('/ajudar/pix.png')
def donation_pix_qr(req:Request):
    key=os.getenv('SOS_DONATION_PIX_KEY','').strip()
    name=os.getenv('SOS_DONATION_PIX_NAME','').strip()
    city=os.getenv('SOS_DONATION_PIX_CITY','').strip()
    if not key or not name or not city:raise HTTPException(404,'QR Code ainda não configurado.')
    try:payload=pix_static_code(key,name,city)
    except ValueError:raise HTTPException(400,'Configuração Pix inválida.')
    import qrcode
    out=io.BytesIO()
    image=qrcode.make(payload,box_size=8,border=4)
    image.save(out,format='PNG')
    return Response(out.getvalue(),media_type='image/png',headers={'Cache-Control':'no-store'})

@app.get('/ajudar')
def support(req:Request):
    pix=clean(os.getenv('SOS_DONATION_PIX_KEY'),200)
    # Nenhuma conta, contato ou chave fictícia é exibida como oficial.
    qr=clean(os.getenv('SOS_DONATION_QR_IMAGE'),300)
    if not (qr.startswith('/static/img/') or qr.startswith('/static/uploads/')):qr=''
    donation={
        'enabled':bool(pix),
        'pix_key':pix,
        'pix_type':clean(os.getenv('SOS_DONATION_PIX_TYPE','Chave Pix'),50),
        'pix_name':clean(os.getenv('SOS_DONATION_PIX_NAME','ONG responsável'),100),
        'receipt_contact':clean(os.getenv('SOS_DONATION_RECEIPT'),160),
        'qr_image':(qr if qr else ('/ajudar/pix.png' if pix and os.getenv('SOS_DONATION_PIX_NAME') and os.getenv('SOS_DONATION_PIX_CITY') else '')) if pix else ''
    }
    return page(req,'support.html',kind='donate',donation=donation)
@app.get('/voluntariado')
def volunteer_page(req:Request):return page(req,'support.html',kind='volunteer')
@app.post('/voluntariado')
async def volunteer(req:Request):
    u=require_user(req);f=await req.form();secure_form(req,f)
    area=clean(f.get('area'),100);availability=clean(f.get('availability'),150);message=clean(f.get('message'),1000)
    if not area or not availability or len(message)<15:return go('/voluntariado',req,'Preencha todos os campos para se candidatar.',True)
    with db() as c:
        try:c.execute('INSERT INTO volunteers(user_id,area,availability,message,created_at) VALUES(?,?,?,?,?)',(u['id'],area,availability,message,now()))
        except sqlite3.IntegrityError:return go('/minha-conta',req,'Você já possui uma candidatura de voluntariado.',True)
        audit(c,u['id'],'candidatura_voluntario')
    return go('/minha-conta',req,'Candidatura enviada. A equipe fará a avaliação.')

# Recuperação de senha opcional via SMTP: nenhum link é exposto pela web ou terminal.
@app.get('/recuperar')
def recover_page(req:Request):return page(req,'recover.html',mode='request')

@app.post('/recuperar')
async def recover(req:Request):
    f=await req.form();secure_form(req,f)
    identifier=clean(f.get('email'),160).lower()
    host=os.environ.get('SOS_SMTP_HOST')
    sender=os.environ.get('SOS_SMTP_FROM')
    if not host or not sender:
        return page(req,'message.html',heading='Recuperação indisponível',message='O envio de e-mail ainda não foi configurado nesta instalação. Entre em contato com o responsável pelo projeto.')
    with db() as c:
        u=c.execute('SELECT * FROM users WHERE lower(email)=? AND active=1',(identifier,)).fetchone()
        if u:
            recent=(datetime.now()-timedelta(minutes=15)).isoformat(timespec='seconds')
            amount=c.execute('SELECT COUNT(*) FROM password_resets WHERE user_id=? AND requested_at>=?',(u['id'],recent)).fetchone()[0]
            if amount<3:
                token=secrets.token_urlsafe(32)
                token_hash=hashlib.sha256(token.encode()).hexdigest()
                c.execute('INSERT INTO password_resets(user_id,token_hash,requested_at) VALUES(?,?,?)',(u['id'],token_hash,now()))
                base=os.environ.get('SOS_PUBLIC_URL','http://127.0.0.1:8000').rstrip('/')
                letter=EmailMessage()
                letter['Subject']='SOS Patinhas — recuperar acesso'
                letter['From']=sender
                letter['To']=u['email']
                letter.set_content(f'Você solicitou a redefinição de senha do SOS Patinhas. O link expira em uma hora:\n{base}/redefinir/{token}\nSe não foi você, ignore esta mensagem.')
                try:
                    with smtplib.SMTP(host,int(os.environ.get('SOS_SMTP_PORT','587')),timeout=8) as smtp:
                        smtp.starttls()
                        username=os.environ.get('SOS_SMTP_USER')
                        password=os.environ.get('SOS_SMTP_PASSWORD')
                        if username and password:smtp.login(username,password)
                        smtp.send_message(letter)
                except (OSError,smtplib.SMTPException,ValueError):
                    c.execute('DELETE FROM password_resets WHERE token_hash=?',(token_hash,))
                    return page(req,'message.html',heading='Envio não concluído',message='O servidor de e-mail está indisponível. Tente novamente mais tarde.')
    return page(req,'message.html',heading='Solicitação recebida',message='Se houver uma conta ativa para este e-mail, enviaremos instruções para recuperar o acesso.')

@app.get('/redefinir/{token}')
def reset_page(req:Request,token:str):
    key=hashlib.sha256(token.encode()).hexdigest()
    deadline=(datetime.now()-timedelta(hours=1)).isoformat(timespec='seconds')
    with db() as c: found=c.execute('SELECT id FROM password_resets WHERE token_hash=? AND used_at IS NULL AND requested_at>?',(key,deadline)).fetchone()
    if not found:raise HTTPException(400,'Link expirado ou já utilizado.')
    return page(req,'recover.html',mode='reset',token=token)

@app.post('/redefinir/{token}')
async def reset_password(req:Request,token:str):
    f=await req.form();secure_form(req,f)
    password=str(f.get('password') or '')
    if len(password)<10 or password!=f.get('confirm'):
        return go('/redefinir/'+token,req,'Use uma senha de pelo menos 10 caracteres e confirme corretamente.',True)
    key=hashlib.sha256(token.encode()).hexdigest()
    deadline=(datetime.now()-timedelta(hours=1)).isoformat(timespec='seconds')
    with db() as c:
        entry=c.execute('SELECT * FROM password_resets WHERE token_hash=? AND used_at IS NULL AND requested_at>?',(key,deadline)).fetchone()
        if not entry:raise HTTPException(400,'Link expirado ou já utilizado.')
        c.execute('UPDATE users SET password_hash=? WHERE id=?',(ph.hash(password),entry['user_id']))
        c.execute('UPDATE password_resets SET used_at=? WHERE id=?',(now(),entry['id']))
        audit(c,entry['user_id'],'senha_recuperada')
    return go('/entrar',req,'Senha redefinida. Faça login com sua nova senha.')

@app.get('/minha-conta/exportar')
def export_data(req:Request):
    u=require_user(req)
    profile={k:v for k,v in u.items() if k!='password_hash'}
    with db() as c:
        apps=[dict(x) for x in c.execute('SELECT animal_id,household,experience,motivation,status,created_at,review_reason FROM adoptions WHERE user_id=?',(u['id'],))]
        volunteering=[dict(x) for x in c.execute('SELECT area,availability,message,status,created_at FROM volunteers WHERE user_id=?',(u['id'],))]
        notices=[dict(x) for x in c.execute('SELECT title,body,created_at FROM notifications WHERE user_id=?',(u['id'],))]
    payload=json.dumps({'usuario':profile,'solicitacoes':apps,'voluntariado':volunteering,'notificacoes':notices},ensure_ascii=False,indent=2)
    return Response(payload,media_type='application/json; charset=utf-8',headers={'Content-Disposition':'attachment; filename="meus-dados-sos-patinhas.json"','Cache-Control':'no-store'})

@app.post('/minha-conta/exclusao')
async def request_deletion(req:Request):
    u=require_user(req);f=await req.form();secure_form(req,f)
    try:valid=ph.verify(u['password_hash'],str(f.get('password') or ''))
    except (argon_exc.VerifyMismatchError,argon_exc.VerificationError,argon_exc.InvalidHashError):valid=False
    if not valid:return go('/minha-conta',req,'Confirme a senha correta para solicitar a exclusão dos dados.',True)
    with db() as c:
        existing=c.execute("SELECT id FROM privacy_requests WHERE user_id=? AND status='Pendente'",(u['id'],)).fetchone()
        if existing:return go('/minha-conta',req,'Você já possui uma solicitação de privacidade pendente.',True)
        c.execute("INSERT INTO privacy_requests(user_id,request_type,created_at) VALUES(?,'Exclusão/anonimização',?)",(u['id'],now()))
        audit(c,u['id'],'lgpd_solicitacao_exclusao')
    return go('/minha-conta',req,'Solicitação enviada para revisão pela equipe responsável. Seus dados ainda não foram excluídos.')

@app.get('/painel/privacidade')
def privacy_admin(req:Request):
    u=require_user(req,True)
    if u['role']!='admin':raise HTTPException(403,'Somente administradores')
    with db() as c:
        rows=[dict(x) for x in c.execute('SELECT p.*,u.name,u.email FROM privacy_requests p JOIN users u ON u.id=p.user_id ORDER BY p.id DESC')]
    return page(req,'admin.html',kind='privacy',rows=rows,active='privacidade')

@app.post('/painel/privacidade/{pid}')
async def mark_privacy(req:Request,pid:int):
    u=require_user(req,True)
    if u['role']!='admin':raise HTTPException(403,'Somente administradores')
    f=await req.form();secure_form(req,f)
    if f.get('status') not in ('Pendente','Em análise','Resolvida'):raise HTTPException(400,'Status inválido')
    with db() as c:
        c.execute('UPDATE privacy_requests SET status=?,resolved_at=? WHERE id=?',(f.get('status'),now() if f.get('status')=='Resolvida' else None,pid))
        audit(c,u['id'],'lgpd_solicitacao_status',str(pid))
    return go('/painel/privacidade',req,'Solicitação atualizada. A exclusão dos dados deve ser executada por processo aprovado.')

# Solicitações de acolhimento/entrega — não são resgates automaticamente.
@app.get('/entregar-animal')
def intake_page(req:Request):
    require_user(req)
    return page(req,'intake.html')

@app.post('/entregar-animal')
async def intake_create(req:Request):
    u=require_user(req);f=await req.form();secure_form(req,f)
    species=clean(f.get('species'),50);age=clean(f.get('age'),80);location=clean(f.get('location'),250)
    condition=clean(f.get('condition'),900);reason=clean(f.get('reason'),1400)
    if species not in ('Cão','Gato','Outro') or len(location)<7 or len(condition)<15 or len(reason)<15:
        return go('/entregar-animal',req,'Descreva o animal, local, condições e motivo do pedido.',True)
    with db() as c:
        count=c.execute("SELECT COUNT(*) FROM intakes WHERE user_id=? AND created_at>?",(u['id'],(datetime.now()-timedelta(days=1)).isoformat(timespec='seconds'))).fetchone()[0]
        if count>=3:return go('/minha-conta',req,'Limite diário de solicitações atingido.',True)
        c.execute('INSERT INTO intakes(user_id,species,age,location,condition,reason,created_at) VALUES(?,?,?,?,?,?,?)',(u['id'],species,age,location,condition,reason,now()))
        audit(c,u['id'],'solicitacao_acolhimento')
    return go('/minha-conta',req,'Pedido recebido para análise. Isto não confirma o acolhimento do animal.')

@app.get('/voluntariado/atividades')
def volunteer_tasks(req:Request):
    u=require_user(req)
    with db() as c:
        approved=c.execute("SELECT 1 FROM volunteers WHERE user_id=? AND status='Aprovado'",(u['id'],)).fetchone()
        if not approved and u['role'] not in ('admin','funcionario'):raise HTTPException(403,'Acesso reservado a voluntários aprovados.')
        tasks=[dict(x) for x in c.execute('SELECT * FROM volunteer_tasks WHERE active=1 ORDER BY id DESC')]
    return page(req,'volunteer_tasks.html',rows=tasks)

@app.get('/painel/atividades')
def volunteer_tasks_admin(req:Request):
    require_user(req,True)
    with db() as c:rows=[dict(x) for x in c.execute('SELECT * FROM volunteer_tasks ORDER BY id DESC')]
    return page(req,'volunteer_tasks_admin.html',rows=rows,active='atividades')

@app.post('/painel/atividades')
async def volunteer_task_create(req:Request):
    actor=require_user(req,True);f=await req.form();secure_form(req,f)
    title=clean(f.get('title'),130);description=clean(f.get('description'),1000);when_at=clean(f.get('when_at'),60)
    if len(title)<5 or len(description)<15:return go('/painel/atividades',req,'Descreva a atividade e o título.',True)
    with db() as c:
        c.execute('INSERT INTO volunteer_tasks(title,description,when_at,created_at) VALUES(?,?,?,?)',(title,description,when_at,now()))
        audit(c,actor['id'],'atividade_criada',title)
    return go('/painel/atividades',req,'Atividade publicada.')

@app.post('/painel/atividades/{tid}/alternar')
async def volunteer_task_toggle(req:Request,tid:int):
    actor=require_user(req,True);f=await req.form();secure_form(req,f)
    with db() as c:
        c.execute('UPDATE volunteer_tasks SET active=1-active WHERE id=?',(tid,))
        audit(c,actor['id'],'atividade_alternada',str(tid))
    return go('/painel/atividades',req,'Atividade atualizada.')

@app.get('/painel/acolhimentos')
def intakes_admin(req:Request):
    require_user(req,True)
    with db() as c:
        rows=[dict(x) for x in c.execute('SELECT i.*,u.name,u.email,u.phone FROM intakes i JOIN users u ON u.id=i.user_id ORDER BY i.id DESC')]
    return page(req,'admin.html',kind='intakes',rows=rows,active='acolhimentos')

@app.post('/painel/acolhimentos/{iid}')
async def intake_action(req:Request,iid:int):
    u=require_user(req,True);f=await req.form();secure_form(req,f)
    status=clean(f.get('status'),30)
    if status not in ('Recebido','Em análise','Aprovado para contato','Não aprovado'):raise HTTPException(400,'Situação inválida')
    with db() as c:
        a=c.execute('SELECT user_id FROM intakes WHERE id=?',(iid,)).fetchone()
        if not a:raise HTTPException(404,'Pedido não encontrado')
        c.execute('UPDATE intakes SET status=? WHERE id=?',(status,iid))
        notify(c,a['user_id'],'Pedido de acolhimento',f'Seu pedido foi atualizado para: {status}.')
        audit(c,u['id'],'acolhimento_status',f'{iid}: {status}')
    return go('/painel/acolhimentos',req,'Pedido atualizado. Cadastre um relatório de resgate somente após realização real.')

@app.get('/painel/mensagens')
def messages_admin(req:Request):
    require_user(req,True)
    with db() as c:
        recent=[dict(x) for x in c.execute('SELECT n.title,n.body,n.created_at,u.name FROM notifications n JOIN users u ON u.id=n.user_id ORDER BY n.id DESC LIMIT 30')]
    return page(req,'admin.html',kind='messages',rows=recent,active='mensagens')

@app.post('/painel/mensagens')
async def send_message(req:Request):
    u=require_user(req,True);f=await req.form();secure_form(req,f)
    title=clean(f.get('title'),100);message=clean(f.get('message'),1500);target=clean(f.get('target'),25)
    if len(title)<5 or len(message)<10 or target not in ('adotantes','voluntarios','todos'):
        return go('/painel/mensagens',req,'Preencha título, mensagem e público-alvo.',True)
    with db() as c:
        sql="SELECT id FROM users WHERE active=1 AND role='adotante'"
        if target=='todos':sql='SELECT id FROM users WHERE active=1'
        if target=='voluntarios':sql="SELECT user_id id FROM volunteers WHERE status='Aprovado'"
        targets=c.execute(sql).fetchall()
        for t in targets:notify(c,t['id'],title,message)
        audit(c,u['id'],'notificacao_massa',f'{target}: {len(targets)} usuários')
    return go('/painel/mensagens',req,f'Mensagem disponibilizada no painel de {len(targets)} usuário(s).')

# ADMIN: visão consolidada
@app.get('/painel')
def admin_dashboard(req:Request):
    require_user(req,True)
    with db() as c:
        scheduled_alerts(c)
        metrics={
          'animais':c.execute('SELECT COUNT(*) FROM animals').fetchone()[0],
          'adotaveis':c.execute("SELECT COUNT(*) FROM animals WHERE status='Apto para adoção'").fetchone()[0],
          'solicitacoes':c.execute("SELECT COUNT(*) FROM adoptions WHERE status='Em análise'").fetchone()[0],
          'denuncias':c.execute("SELECT COUNT(*) FROM complaints WHERE status NOT IN ('Resgate realizado','Não procedente')").fetchone()[0],
          'resgates':c.execute('SELECT COUNT(*) FROM rescues').fetchone()[0],
          'adotados':c.execute("SELECT COUNT(*) FROM animals WHERE status='Adotado'").fetchone()[0],
          'doacoes':c.execute('SELECT COALESCE(SUM(amount),0) FROM donations WHERE kind="Financeira"').fetchone()[0],
          'voluntarios':c.execute("SELECT COUNT(*) FROM volunteers WHERE status='Pendente'").fetchone()[0],
        }
        recent=[dict(x) for x in c.execute('SELECT a.id,a.status,a.created_at,u.name applicant,n.name animal FROM adoptions a JOIN users u ON u.id=a.user_id JOIN animals n ON n.id=a.animal_id ORDER BY a.id DESC LIMIT 6')]
        followups=[dict(x) for x in c.execute('SELECT f.*, n.name animal FROM followups f JOIN adoptions a ON a.id=f.adoption_id JOIN animals n ON n.id=a.animal_id WHERE f.contacted_at IS NULL ORDER BY f.due_date LIMIT 5')]
    return page(req,'panel.html',metrics=metrics,recent=recent,followups=followups,active='inicio')

@app.get('/painel/resgates')
def rescues_admin(req:Request):
    require_user(req,True)
    with db() as c: rows=[dict(x) for x in c.execute('SELECT r.*,a.id animal_id FROM rescues r LEFT JOIN animals a ON a.rescue_id=r.id ORDER BY r.id DESC')]
    return page(req,'admin.html',kind='rescues',rows=rows,active='resgates')
@app.post('/painel/resgates')
async def rescue_create(req:Request):
    u=require_user(req,True);f=await req.form();secure_form(req,f)
    fields=[clean(f.get(k),500) for k in ('provisional_name','species','sex','size','rescue_date','location','initial_health')]
    if not all(fields):return go('/painel/resgates',req,'Preencha os dados obrigatórios do resgate.',True)
    try:photo=await upload_private(f.get('photo'))
    except ValueError as e:return go('/painel/resgates',req,str(e),True)
    protocol='RES-'+datetime.now().strftime('%Y%m%d')+'-'+secrets.token_hex(3).upper()
    with db() as c:
        c.execute('INSERT INTO rescues(protocol,provisional_name,species,sex,size,rescue_date,location,initial_health,behavior,photo,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
        (protocol,*fields,clean(f.get('behavior'),700),photo,u['id'],now()))
        audit(c,u['id'],'resgate_criado',protocol)
    return go('/painel/resgates',req,'Relatório de resgate criado. Este registro é imutável.')

@app.get('/painel/resgates/{rid}/foto')
def rescue_photo(req:Request,rid:int):
    require_user(req,True)
    with db() as c:r=c.execute('SELECT photo FROM rescues WHERE id=?',(rid,)).fetchone()
    if not r or not r['photo']:raise HTTPException(404,'Foto não encontrada')
    path=PRIVATE/Path(r['photo']).name
    if not path.is_file():raise HTTPException(404,'Arquivo indisponível')
    return FileResponse(path,headers={'Cache-Control':'no-store'})

@app.get('/painel/animais')
def animals_admin(req:Request, editar:int=0):
    require_user(req,True)
    with db() as c:
        rows=[dict(x) for x in c.execute('SELECT a.*,r.protocol FROM animals a LEFT JOIN rescues r ON r.id=a.rescue_id ORDER BY a.id DESC')]
        rescues=[dict(x) for x in c.execute('SELECT * FROM rescues WHERE id NOT IN (SELECT rescue_id FROM animals WHERE rescue_id IS NOT NULL) ORDER BY id DESC')]
        editing=rowdict(c.execute('SELECT * FROM animals WHERE id=?',(editar,)).fetchone()) if editar else None
        gallery=[dict(x) for x in c.execute('SELECT * FROM animal_photos WHERE animal_id=?',(editar,))] if editar else []
        history=[dict(x) for x in c.execute('SELECT * FROM animal_edits WHERE animal_id=? ORDER BY id DESC LIMIT 30',(editar,))] if editar else []
    return page(req,'admin.html',kind='animals',rows=rows,rescues=rescues,editing=editing,states=ANIMAL_STATES,active='animais',gallery=gallery,history=history)
@app.post('/painel/animais')
async def animal_save(req:Request):
    u=require_user(req,True);f=await req.form();secure_form(req,f)
    aid=int(f.get('id') or 0)
    fields=[clean(f.get(x),800) for x in ('name','species','breed','age','sex','size','description','health','status')]
    name,species,breed,age,sex,size,description,health,status=fields
    neutered=1 if f.get('neutered') else 0; vaccinated=1 if f.get('vaccinated') else 0; dewormed=1 if f.get('dewormed') else 0
    if not all([name,species,breed,age,sex,size,health]) or status not in ANIMAL_STATES:
        return go('/painel/animais',req,'Preencha nome, espécie, raça, idade, sexo, porte e saúde.',True)
    if status=='Apto para adoção' and not neutered:return go('/painel/animais',req,'Para ficar apto à adoção, o animal deve ter castração registrada.',True)
    if status=='Adotado' and not aid:return go('/painel/animais',req,'Uma adoção só é concluída após termo assinado e avaliação.',True)
    if status=='Em processo de adoção' and not aid:return go('/painel/animais',req,'Inicie a triagem de uma solicitação de adoção para usar este status.',True)
    reason=clean(f.get('reason'),350)
    if status in ('Fugiu','Óbito') and len(reason)<8:return go('/painel/animais',req,'Informe justificativa para Fugiu ou Óbito (mínimo 8 caracteres).',True)
    vaccination_due=clean(f.get('vaccination_due'),10)
    if vaccination_due:
        try:datetime.strptime(vaccination_due,'%Y-%m-%d')
        except ValueError:return go('/painel/animais',req,'Data de vacina inválida.',True)
    try:
        photo=await upload_image(f.get('photo'))
        more=f.getlist('more_photos')[:4]
        extras=[p for p in [await upload_image(v) for v in more] if p]
    except ValueError as e:return go('/painel/animais',req,str(e),True)
    with db() as c:
        if aid:
            old=c.execute('SELECT * FROM animals WHERE id=?',(aid,)).fetchone()
            if not old:raise HTTPException(404,'Animal não localizado')
            if old['status']=='Adotado' and status!='Adotado':return go('/painel/animais',req,'Altere o status de adoções concluídas somente após revisão formal.',True)
            if status in ('Adotado','Em processo de adoção') and status!=old['status']:return go('/painel/animais',req,'Situações de adoção são definidas pelo processo de triagem e termo assinado.',True)
            c.execute('UPDATE animals SET name=?,species=?,breed=?,age=?,sex=?,size=?,description=?,health=?,status=?,neutered=?,vaccinated=?,dewormed=?,photo=?,vaccination_due=?,updated_at=? WHERE id=?',
                (name,species,breed,age,sex,size,description,health,status,neutered,vaccinated,dewormed,photo or old['photo'],vaccination_due or None,now(),aid))
            edits={key:[old[key],new] for key,new in [('name',name),('breed',breed),('age',age),('sex',sex),('size',size),('description',description),('health',health),('status',status),('neutered',neutered),('vaccinated',vaccinated),('dewormed',dewormed),('vaccination_due',vaccination_due or None)] if old[key]!=new}
            if photo:edits['photo']=['anterior','alterada']
            if edits:c.execute('INSERT INTO animal_edits(animal_id,actor_id,details,created_at) VALUES(?,?,?,?)',(aid,u['id'],json.dumps(edits,ensure_ascii=False),now()))
            if status!=old['status']:
                c.execute('INSERT INTO animal_changes(animal_id,actor_id,old_status,new_status,reason,changed_at) VALUES(?,?,?,?,?,?)',(aid,u['id'],old['status'],status,reason,now()))
        else:
            rid=int(f.get('rescue_id') or 0)
            res=c.execute('SELECT * FROM rescues WHERE id=?',(rid,)).fetchone()
            if not res:return go('/painel/animais',req,'Selecione um relatório de resgate antes do cadastro definitivo.',True)
            if c.execute('SELECT id FROM animals WHERE rescue_id=?',(rid,)).fetchone():return go('/painel/animais',req,'Este resgate já possui animal cadastrado.',True)
            if name.lower()==res['provisional_name'].lower(): return go('/painel/animais',req,'Defina um nome definitivo, diferente do provisório.',True)
            if not photo:return go('/painel/animais',req,'Envie ao menos uma foto do animal.',True)
            c.execute('INSERT INTO animals(rescue_id,name,species,breed,age,sex,size,description,health,status,neutered,vaccinated,dewormed,photo,vaccination_due,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (rid,name,species,breed,age,sex,size,description,health,status,neutered,vaccinated,dewormed,photo,vaccination_due or None,now(),now()))
            aid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute('INSERT INTO animal_changes(animal_id,actor_id,old_status,new_status,reason,changed_at) VALUES(?,?,?,?,?,?)',(aid,u['id'],None,status,'Cadastro definitivo',now()))
        for extra in extras:
            c.execute('INSERT INTO animal_photos(animal_id,photo,created_at) VALUES(?,?,?)',(aid,extra,now()))
        audit(c,u['id'],'animal_salvo',f'animal {aid}')
    return go('/painel/animais',req,'Cadastro de animal salvo!')

@app.get('/painel/solicitacoes')
def adoptions_admin(req:Request,status:str=''):
    require_user(req,True)
    with db() as c:
        sql='SELECT a.*,u.name applicant,u.email,u.phone,u.restricted_reason,n.name animal,n.photo,n.status animal_status FROM adoptions a JOIN users u ON u.id=a.user_id JOIN animals n ON n.id=a.animal_id'
        params=[]
        if status in ('Em análise','Aprovado','Recusado','Concluído','Desistiu'): sql+=' WHERE a.status=?';params=[status]
        sql+=' ORDER BY a.animal_id,a.created_at,a.id'
        rows=[dict(x) for x in c.execute(sql,params)]
    return page(req,'admin.html',kind='adoptions',rows=rows,active='solicitacoes',filter_status=status)
@app.post('/painel/solicitacoes/{adoption_id}')
async def adoption_action(req:Request, adoption_id:int):
    u=require_user(req,True);f=await req.form();secure_form(req,f)
    action=str(f.get('action') or '');reason=clean(f.get('reason'),700)
    try:
        document=await upload_private(f.get('signed_term'),'pdf') if action=='concluir' else None
        evaluation_file=await upload_private(f.get('evaluation_file')) if action=='aprovar' else None
    except ValueError as e:return go('/painel/solicitacoes',req,str(e),True)
    evaluation_notes=clean(f.get('evaluation_notes'),1600)
    with db() as c:
        a=c.execute('SELECT * FROM adoptions WHERE id=?',(adoption_id,)).fetchone()
        if not a:raise HTTPException(404,'Solicitação inexistente')
        animal=c.execute('SELECT * FROM animals WHERE id=?',(a['animal_id'],)).fetchone()
        if action=='iniciar' and a['status']=='Em análise' and animal['status']=='Apto para adoção':
            first=c.execute("SELECT id FROM adoptions WHERE animal_id=? AND status='Em análise' ORDER BY created_at,id LIMIT 1",(a['animal_id'],)).fetchone()
            if not first or first['id']!=adoption_id:return go('/painel/solicitacoes',req,'Respeite a ordem de chegada da fila.',True)
            c.execute("UPDATE animals SET status='Em processo de adoção',updated_at=? WHERE id=?",(now(),a['animal_id']))
            c.execute("UPDATE adoptions SET in_review=1 WHERE id=?",(adoption_id,))
        elif action=='aprovar' and a['status']=='Em análise' and a['in_review'] and animal['status']=='Em processo de adoção':
            if len(evaluation_notes)<15:return go('/painel/solicitacoes',req,'Registre o parecer de triagem com pelo menos 15 caracteres.',True)
            c.execute("UPDATE adoptions SET status='Aprovado',reviewed_at=?,evaluation_notes=?,evaluation_file=? WHERE id=?",(now(),evaluation_notes,evaluation_file,adoption_id))
            notify(c,a['user_id'],'Solicitação aprovada',f'A solicitação de adoção de {animal["name"]} foi aprovada. Aguarde o termo.')
        elif action=='recusar' and a['status']=='Em análise' and ((a['in_review'] and animal['status']=='Em processo de adoção') or animal['status']=='Apto para adoção'):
            if len(reason)<8:return go('/painel/solicitacoes',req,'A recusa exige justificativa (mínimo 8 caracteres).',True)
            c.execute("UPDATE adoptions SET status='Recusado',in_review=0,review_reason=?,evaluation_notes=?,reviewed_at=? WHERE id=?",(reason,evaluation_notes or None,now(),adoption_id))
            notify(c,a['user_id'],'Atualização da adoção',f'A solicitação de {animal["name"]} não foi aprovada. Consulte sua conta.')
            if animal['status']=='Em processo de adoção':
                c.execute("UPDATE animals SET status='Apto para adoção',updated_at=? WHERE id=?",(now(),a['animal_id']))
                next_app=c.execute("SELECT user_id FROM adoptions WHERE animal_id=? AND status='Em análise' ORDER BY created_at,id LIMIT 1",(a['animal_id'],)).fetchone()
                if next_app:notify(c,next_app['user_id'],'Próximo na fila',f'A solicitação para {animal["name"]} é a próxima a ser avaliada.')
        elif action=='concluir' and a['status']=='Aprovado' and document:
            c.execute("UPDATE adoptions SET status='Concluído',signed_term=?,finalized_at=? WHERE id=?",(document,now(),adoption_id))
            c.execute("UPDATE animals SET status='Adotado',updated_at=? WHERE id=?",(now(),a['animal_id']))
            for days in (15,90,180):
                c.execute('INSERT INTO followups(adoption_id,due_date) VALUES(?,?)',(adoption_id,(datetime.now()+timedelta(days=days)).strftime('%Y-%m-%d')))
            c.execute("UPDATE adoptions SET status='Recusado',review_reason='Animal adotado por outro candidato',reviewed_at=? WHERE animal_id=? AND id<>? AND status='Em análise'",(now(),a['animal_id'],adoption_id))
            notify(c,a['user_id'],'Adoção concluída',f'A adoção de {animal["name"]} foi concluída! Parabéns!')
        else:return go('/painel/solicitacoes',req,'Ação não permitida para o estado atual.',True)
        audit(c,u['id'],'avaliacao_adocao',f'{adoption_id}: {action}')
    return go('/painel/solicitacoes',req,'Solicitação atualizada.')

@app.get('/painel/solicitacoes/{adoption_id}/anexo')
def evaluation_attachment(req:Request,adoption_id:int):
    require_user(req,True)
    with db() as c:a=c.execute('SELECT evaluation_file FROM adoptions WHERE id=?',(adoption_id,)).fetchone()
    if not a or not a['evaluation_file']:raise HTTPException(404,'Anexo indisponível')
    path=PRIVATE/Path(a['evaluation_file']).name
    if not path.is_file():raise HTTPException(404,'Arquivo não encontrado')
    return FileResponse(path,headers={'Cache-Control':'no-store'})

@app.get('/painel/solicitacoes/{adoption_id}/termo')
def adoption_pdf(req:Request,adoption_id:int):
    u=require_user(req)
    with db() as c:
        a=c.execute('SELECT a.*,n.name animal,n.species,u.name adopter,u.cpf FROM adoptions a JOIN animals n ON n.id=a.animal_id JOIN users u ON u.id=a.user_id WHERE a.id=?',(adoption_id,)).fetchone()
    if not a:raise HTTPException(404,'Solicitação não encontrada.')
    if u['role'] not in ('funcionario','admin') and a['user_id']!=u['id']:raise HTTPException(403,'Sem acesso a este termo.')
    if a['status'] not in ('Aprovado','Concluído'):raise HTTPException(400,'Termo disponível apenas após aprovação.')
    b=io.BytesIO();p=canvas.Canvas(b,pagesize=A4);w,h=A4
    p.setTitle('Termo de Responsabilidade e Adoção – SOS Patinhas')
    p.setFont('Helvetica-Bold',18);p.drawString(55,h-70,'SOS PATINHAS')
    p.setFont('Helvetica-Bold',13);p.drawString(55,h-108,'TERMO DE RESPONSABILIDADE E ADOCAO')
    p.setFont('Helvetica',11)
    content=[f'Adotante: {a["adopter"]}',f'CPF: {a["cpf"] or "Não informado"}',f'Animal: {a["animal"]}  |  Especie: {a["species"]}',f'Solicitacao: #{a["id"]}  |  Data: {a["created_at"][:10]}', '',
    'Declaro assumir, de forma responsavel, os cuidados e a guarda do animal acima.',
    'Comprometo-me a fornecer alimentacao, abrigo, cuidados e assistencia',
    'veterinaria adequados, respeitando o bem-estar e a legislacao vigente.',
    'Entendo que a ONG podera entrar em contato para acompanhamento pos-adocao.',
    '', 'Assinatura do adotante: _____________________________________',
    '', 'Data: ____/____/________', '',
    'MODELO ACADEMICO. Revisar juridicamente antes de uso real.']
    y=h-150
    for line in content:
        if line:y-=22;p.drawString(55,y,line[:98])
        else:y-=13
    p.save();b.seek(0)
    return Response(content=b.getvalue(),media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="termo-adocao-{adoption_id}.pdf"'})

@app.get('/adocoes/{adoption_id}/documento')
def signed_document(req:Request,adoption_id:int):
    u=require_user(req)
    with db() as c:
        doc=c.execute('SELECT user_id,signed_term,status FROM adoptions WHERE id=?',(adoption_id,)).fetchone()
    if not doc or not doc['signed_term'] or doc['status']!='Concluído':
        raise HTTPException(404,'Documento assinado não está disponível.')
    if u['role'] not in ('admin','funcionario') and u['id']!=doc['user_id']:
        raise HTTPException(403,'Você não tem acesso a esse documento.')
    path=PRIVATE/Path(doc['signed_term']).name
    if not path.is_file():raise HTTPException(404,'Documento não localizado no servidor.')
    return FileResponse(path,media_type='application/pdf',filename=f'termo-assinado-{adoption_id}.pdf',headers={'Cache-Control':'no-store'})

@app.get('/painel/denuncias')
def complaints_admin(req:Request):
    require_user(req,True)
    with db() as c:
        rows=[dict(x) for x in c.execute('SELECT c.*,u.name reporter FROM complaints c LEFT JOIN users u ON u.id=c.reporter_id ORDER BY c.id DESC')]
    return page(req,'admin.html',kind='complaints',rows=rows,active='denuncias',states=DENUNCIA_STATES)
@app.post('/painel/denuncias/{cid}')
async def complaint_action(req:Request,cid:int):
    u=require_user(req,True);f=await req.form();secure_form(req,f)
    status=clean(f.get('status'),50)
    if status not in DENUNCIA_STATES:raise HTTPException(400,'Status inválido')
    with db() as c:
        cur=c.execute('UPDATE complaints SET status=? WHERE id=?',(status,cid))
        if cur.rowcount==0:raise HTTPException(404,'Denúncia não encontrada')
        audit(c,u['id'],'denuncia_status',f'{cid}: {status}')
    return go('/painel/denuncias',req,'Denúncia atualizada.')

@app.get('/painel/evidencia/{cid}')
def download_evidence(req:Request,cid:int):
    require_user(req,True)
    with db() as c:r=c.execute('SELECT evidence FROM complaints WHERE id=?',(cid,)).fetchone()
    if not r or not r['evidence']:raise HTTPException(404,'Evidência não encontrada')
    path=PRIVATE/Path(r['evidence']).name
    if not path.is_file():raise HTTPException(404,'Arquivo não encontrado')
    return FileResponse(path,filename='evidencia'+path.suffix)

@app.get('/painel/doacoes')
def donations_admin(req:Request):
    require_user(req,True)
    with db() as c:
        rows=[dict(x) for x in c.execute('SELECT * FROM donations ORDER BY id DESC LIMIT 100')]
        donors=[dict(x) for x in c.execute("SELECT COALESCE(NULLIF(TRIM(donor),''),'Anônimo') donor,COUNT(*) total,COALESCE(SUM(CASE WHEN kind='Financeira' THEN amount ELSE 0 END),0) amount,COALESCE(SUM(CASE WHEN kind='Material' THEN quantity ELSE 0 END),0) items FROM donations GROUP BY COALESCE(NULLIF(TRIM(donor),''),'Anônimo') ORDER BY total DESC LIMIT 30")]
    return page(req,'admin.html',kind='donations',rows=rows,donors=donors,active='doacoes')
@app.post('/painel/doacoes')
async def donation_create(req:Request):
    u=require_user(req,True);f=await req.form();secure_form(req,f)
    kind=clean(f.get('kind'),30);amount=None;item='';quantity=None
    if kind=='Financeira':
        try:amount=float(str(f.get('amount') or '0').replace(',','.'))
        except ValueError:amount=0
        if not (0<amount<=1_000_000):return go('/painel/doacoes',req,'Informe um valor positivo válido.',True)
    elif kind=='Material':
        item=clean(f.get('item'),300)
        try: quantity=int(f.get('quantity') or 0)
        except ValueError: quantity=0
        if not item or quantity<1:return go('/painel/doacoes',req,'Informe item e quantidade.',True)
    else:return go('/painel/doacoes',req,'Tipo de doação inválido.',True)
    with db() as c:
        c.execute('INSERT INTO donations(kind,amount,item,quantity,condition,donor,method,received_at,recorded_by) VALUES(?,?,?,?,?,?,?,?,?)',
         (kind,amount,item,quantity,clean(f.get('condition'),80),clean(f.get('donor'),120) or 'Anônimo',clean(f.get('method'),70),clean(f.get('received_at'),15) or today(),u['id']))
        audit(c,u['id'],'doacao_registrada',kind)
    return go('/painel/doacoes',req,'Doação registrada (controle interno, sem processamento de pagamento).')

@app.get('/painel/doacoes/{donation_id}/recibo')
def donation_receipt(req:Request,donation_id:int):
    require_user(req,True)
    with db() as c:d=c.execute('SELECT * FROM donations WHERE id=?',(donation_id,)).fetchone()
    if not d:raise HTTPException(404,'Doação não encontrada')
    b=io.BytesIO();p=canvas.Canvas(b,pagesize=A4);_,h=A4
    p.setTitle(f'Recibo simples de doacao {donation_id}')
    p.setFont('Helvetica-Bold',20);p.drawString(55,h-70,'SOS PATINHAS')
    p.setFont('Helvetica-Bold',14);p.drawString(55,h-106,'COMPROVANTE SIMPLES DE RECEBIMENTO')
    p.setFont('Helvetica',11)
    fields=[('Registro',str(donation_id)),('Recebido em',d['received_at']),('Doador',d['donor'] or 'Anonimo'),('Tipo',d['kind'])]
    if d['kind']=='Financeira':
        fields += [('Valor',f'R$ {d["amount"]:.2f}'),('Forma de recebimento',d['method'] or 'Nao informada')]
    else:
        fields += [('Material',d['item'] or ''),('Quantidade',str(d['quantity'])),('Condicao',d['condition'] or 'Nao informada')]
    y=h-155
    for title,value in fields:
        p.setFont('Helvetica-Bold',11);p.drawString(55,y,title+':')
        p.setFont('Helvetica',11);p.drawString(210,y,str(value)[:75]);y-=27
    p.setFont('Helvetica',9)
    p.drawString(55,y-45,'Recibo nao fiscal. Projeto academico demonstrativo - sem validade tributaria.')
    p.save();b.seek(0)
    return Response(b.getvalue(),media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="recibo-doacao-{donation_id}.pdf"','Cache-Control':'no-store'})

@app.get('/painel/voluntarios')
def volunteers_admin(req:Request):
    require_user(req,True)
    with db() as c:rows=[dict(x) for x in c.execute('SELECT v.*,u.name,u.email,u.phone FROM volunteers v JOIN users u ON u.id=v.user_id ORDER BY v.id DESC')]
    return page(req,'admin.html',kind='volunteers',rows=rows,active='voluntarios')
@app.post('/painel/voluntarios/{vid}')
async def volunteer_action(req:Request,vid:int):
    u=require_user(req,True);f=await req.form();secure_form(req,f);status=clean(f.get('status'),30)
    if status not in ('Pendente','Aprovado','Recusado'):raise HTTPException(400,'Status inválido')
    with db() as c:
        v=c.execute('SELECT * FROM volunteers WHERE id=?',(vid,)).fetchone()
        if not v:raise HTTPException(404,'Candidatura não encontrada')
        c.execute('UPDATE volunteers SET status=? WHERE id=?',(status,vid))
        notify(c,v['user_id'],'Voluntariado',f'Sua candidatura foi atualizada para: {status}.')
        audit(c,u['id'],'voluntario_avaliado',str(vid))
    return go('/painel/voluntarios',req,'Candidatura atualizada.')

@app.get('/painel/campanhas')
def campaigns_admin(req:Request):
    require_user(req,True)
    with db() as c:rows=[dict(x) for x in c.execute('SELECT * FROM campaigns ORDER BY id DESC')]
    return page(req,'admin.html',kind='campaigns',rows=rows,active='campanhas')
@app.post('/painel/campanhas')
async def campaign_create(req:Request):
    u=require_user(req,True);f=await req.form();secure_form(req,f)
    title=clean(f.get('title'),160);description=clean(f.get('description'),1000)
    if len(title)<5 or len(description)<15:return go('/painel/campanhas',req,'Título ou descrição muito curta.',True)
    with db() as c:
        c.execute('INSERT INTO campaigns(title,description,type,event_date,created_at) VALUES(?,?,?,?,?)',(title,description,clean(f.get('type'),50) or 'Campanha',clean(f.get('event_date'),20) or None,now()))
        audit(c,u['id'],'campanha_criada',title)
    return go('/painel/campanhas',req,'Campanha publicada na página inicial.')
@app.post('/painel/campanhas/{cid}/alternar')
async def campaign_toggle(req:Request,cid:int):
    u=require_user(req,True);f=await req.form();secure_form(req,f)
    with db() as c:
        c.execute('UPDATE campaigns SET active=1-active WHERE id=?',(cid,))
        audit(c,u['id'],'campanha_alterada',str(cid))
    return go('/painel/campanhas',req,'Visibilidade atualizada.')

@app.get('/painel/acompanhamentos')
def followups_admin(req:Request):
    require_user(req,True)
    with db() as c:rows=[dict(x) for x in c.execute('SELECT f.*,n.name animal,u.name adopter FROM followups f JOIN adoptions a ON a.id=f.adoption_id JOIN animals n ON n.id=a.animal_id JOIN users u ON u.id=a.user_id ORDER BY f.contacted_at IS NOT NULL,f.due_date')]
    return page(req,'admin.html',kind='followups',rows=rows,active='acompanhamentos')
@app.post('/painel/acompanhamentos/{fid}')
async def followup_update(req:Request,fid:int):
    u=require_user(req,True);f=await req.form();secure_form(req,f)
    channel=clean(f.get('channel'),60);notes=clean(f.get('notes'),1500);resched=clean(f.get('reschedule'),10)
    try:photo=await upload_private(f.get('photo'))
    except ValueError as e:return go('/painel/acompanhamentos',req,str(e),True)
    with db() as c:
        if resched and not channel:
            try:datetime.strptime(resched,'%Y-%m-%d')
            except ValueError:return go('/painel/acompanhamentos',req,'Data inválida.',True)
            c.execute('UPDATE followups SET due_date=? WHERE id=? AND contacted_at IS NULL',(resched,fid))
        elif channel and len(notes)>=8:c.execute('UPDATE followups SET channel=?,notes=?,photo=?,contacted_at=? WHERE id=? AND contacted_at IS NULL',(channel,notes,photo,now(),fid))
        else:return go('/painel/acompanhamentos',req,'Informe o canal e a descrição, ou uma nova data.',True)
        audit(c,u['id'],'acompanhamento',str(fid))
    return go('/painel/acompanhamentos',req,'Acompanhamento registrado.')

@app.get('/painel/acompanhamentos/{fid}/foto')
def followup_photo(req:Request,fid:int):
    require_user(req,True)
    with db() as c:r=c.execute('SELECT photo FROM followups WHERE id=?',(fid,)).fetchone()
    if not r or not r['photo']:raise HTTPException(404,'Foto indisponível')
    path=PRIVATE/Path(r['photo']).name
    if not path.is_file():raise HTTPException(404,'Arquivo não encontrado')
    return FileResponse(path,headers={'Cache-Control':'no-store'})

@app.get('/painel/relatorios')
def reports_admin(req:Request):
    require_user(req,True)
    with db() as c:
        stats={
         'denuncias':c.execute('SELECT COUNT(*) FROM complaints').fetchone()[0],
         'resgates':c.execute('SELECT COUNT(*) FROM rescues').fetchone()[0],
         'adocoes':c.execute("SELECT COUNT(*) FROM adoptions WHERE status='Concluído'").fetchone()[0],
         'financeiro':c.execute('SELECT COALESCE(SUM(amount),0) FROM donations WHERE kind="Financeira"').fetchone()[0],
         'materiais':c.execute('SELECT COALESCE(SUM(quantity),0) FROM donations WHERE kind="Material"').fetchone()[0],
        }
        months=[dict(x) for x in c.execute("SELECT substr(finalized_at,1,7) mes,COUNT(*) total FROM adoptions WHERE status='Concluído' GROUP BY substr(finalized_at,1,7) ORDER BY mes DESC LIMIT 12")]
        statuses=[dict(x) for x in c.execute('SELECT status,COUNT(*) total FROM complaints GROUP BY status ORDER BY total DESC')]
    return page(req,'reports.html',stats=stats,months=list(reversed(months)),statuses=statuses,active='relatorios')

REPORT_CONFIG={
 'animais':("SELECT a.id,a.name,a.species,a.breed,a.age,a.size,a.status,a.created_at FROM animals a", ['ID','Animal','Espécie','Raça','Idade','Porte','Situação','Cadastro'], 'a.created_at','a.species','a.status'),
 'resgates':("SELECT r.id,r.protocol,r.species,r.rescue_date,r.location,r.initial_health FROM rescues r",['ID','Protocolo','Espécie','Data','Local','Condição'], 'r.rescue_date','r.species',None),
 'denuncias':("SELECT c.id,c.protocol,c.species,c.occurred_at,c.location,c.status,c.created_at FROM complaints c",['ID','Protocolo','Espécie','Ocorrência','Local','Situação','Registro'],'c.occurred_at','c.species','c.status'),
 'adocoes':("SELECT d.id,n.name,n.species,d.status,d.created_at,d.finalized_at FROM adoptions d JOIN animals n ON n.id=d.animal_id",['ID','Animal','Espécie','Situação','Solicitação','Conclusão'],'COALESCE(d.finalized_at,d.created_at)','n.species','d.status'),
 'doacoes':("SELECT d.id,d.kind,d.donor,d.amount,d.item,d.quantity,d.received_at FROM donations d",['ID','Tipo','Doador','Valor (R$)','Item','Quantidade','Recebimento'],'d.received_at',None,None),
}

def filtered_report(c,what,inicio='',fim='',especie='',status=''):
    if what not in REPORT_CONFIG:raise HTTPException(404,'Relatório inexistente')
    sql,headers,datecol,speccol,statuscol=REPORT_CONFIG[what]
    where=[];params=[]
    for val in (inicio,fim):
        if val:
            try:datetime.strptime(val,'%Y-%m-%d')
            except ValueError:raise HTTPException(400,'Filtro de data inválido')
    if inicio:where.append('substr('+datecol+',1,10)>=?');params.append(inicio)
    if fim:where.append('substr('+datecol+',1,10)<=?');params.append(fim)
    if especie and speccol:
        if especie not in ('Cão','Gato','Outro'):raise HTTPException(400,'Espécie inválida')
        where.append(speccol+'=?');params.append(especie)
    if status and statuscol:where.append(statuscol+'=?');params.append(status[:50])
    if where:sql+=' WHERE '+' AND '.join(where)
    sql+=' ORDER BY 1 DESC LIMIT 5000'
    return headers,c.execute(sql,params).fetchall()

@app.get('/painel/relatorios/{what}.{fmt}')
def reports_export(req:Request,what:str,fmt:str,inicio:str='',fim:str='',especie:str='',status:str=''):
    require_user(req,True)
    if fmt not in ('csv','xlsx','pdf'):raise HTTPException(404,'Formato indisponível')
    with db() as c:headers,rows=filtered_report(c,what,inicio,fim,especie,status)
    if fmt=='csv':
        stream=io.StringIO();stream.write('\ufeff');writer=csv.writer(stream,delimiter=';');writer.writerow(headers)
        for r in rows:
            writer.writerow([("'"+str(v) if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v) if v is not None else '' for v in r])
        return Response(stream.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="relatorio_{what}.csv"'})
    if fmt=='xlsx':
        import xlsxwriter
        output=io.BytesIO();wb=xlsxwriter.Workbook(output,{'in_memory':True,'strings_to_formulas':False,'strings_to_urls':False})
        sh=wb.add_worksheet('SOS Patinhas');heading=wb.add_format({'bold':True,'font_color':'#FFFFFF','bg_color':'#275339','text_wrap':True})
        sh.freeze_panes(1,0);sh.set_column(0,len(headers)-1,21)
        for j,h in enumerate(headers):sh.write(0,j,h,heading)
        for i,r in enumerate(rows,1):
            for j,v in enumerate(r):sh.write(i,j,v if v is not None else '')
        sh.autofilter(0,0,max(1,len(rows)),len(headers)-1)
        wb.close();return Response(output.getvalue(),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':f'attachment; filename="relatorio_{what}.xlsx"'})
    output=io.BytesIO();pdf=canvas.Canvas(output,pagesize=A4)
    w,h=A4;y=h-57
    pdf.setTitle(f'SOS Patinhas — {what}')
    pdf.setFont('Helvetica-Bold',15);pdf.drawString(45,y,'SOS PATINHAS - RELATORIO '+what.upper());y-=20
    pdf.setFont('Helvetica',9);pdf.drawString(45,y,f'Gerado em {today()} | {len(rows)} registro(s) | de {inicio or "inicio"} ate {fim or "hoje"}');y-=25
    pdf.setFont('Helvetica',8)
    for idx,r in enumerate(rows,1):
        parts=[f'{headers[j]}: {str(v or "-")[:55]}' for j,v in enumerate(r)]
        line=f'{idx}. '+'  |  '.join(parts)
        lines=simpleSplit(line,'Helvetica',8,w-90)
        for chunk in lines:
            if y<55:pdf.showPage();y=h-45;pdf.setFont('Helvetica',8)
            pdf.drawString(45,y,chunk);y-=12
        y-=7
    if not rows:pdf.drawString(45,y,'Nenhum registro encontrado para os filtros.')
    pdf.save()
    return Response(output.getvalue(),media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="relatorio_{what}.pdf"'})

@app.get('/painel/adotantes')
def adopters_admin(req:Request):
    require_user(req,True)
    with db() as c:
        rows=[dict(x) for x in c.execute("SELECT u.id,u.name,u.cpf,u.email,u.phone,u.city,u.uf,u.active,u.restricted_reason,COUNT(DISTINCT a.id) adoptions FROM users u LEFT JOIN adoptions a ON a.user_id=u.id AND a.status='Concluído' WHERE u.role='adotante' GROUP BY u.id ORDER BY u.id DESC")]
    return page(req,'adopters.html',rows=rows,active='adotantes')

@app.post('/painel/adotantes/{uid}')
async def adopter_update(req:Request,uid:int):
    actor=require_user(req,True);f=await req.form();secure_form(req,f)
    action=clean(f.get('action'),20);reason=clean(f.get('reason'),400)
    with db() as c:
        target=c.execute("SELECT * FROM users WHERE id=? AND role='adotante'",(uid,)).fetchone()
        if not target:raise HTTPException(404,'Adotante não encontrado')
        if action=='restringir':
            if len(reason)<10:return go('/painel/adotantes',req,'Informe o motivo da restrição (mínimo de 10 caracteres).',True)
            c.execute('UPDATE users SET restricted_reason=? WHERE id=?',(reason,uid))
        elif action=='liberar':c.execute('UPDATE users SET restricted_reason=NULL WHERE id=?',(uid,))
        elif action=='inativar':
            if len(reason)<10:return go('/painel/adotantes',req,'Informe o motivo da inativação.',True)
            c.execute('UPDATE users SET active=0 WHERE id=?',(uid,))
        elif action=='ativar':c.execute('UPDATE users SET active=1 WHERE id=?',(uid,))
        elif action=='editar':
            name=clean(f.get('name'),140);email=clean(f.get('email'),160).lower();phone=digits(f.get('phone'))
            if len(name)<4 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email) or len(phone)<10:
                return go('/painel/adotantes',req,'Confira nome, e-mail e telefone.',True)
            try:c.execute('UPDATE users SET name=?,email=?,phone=? WHERE id=?',(name,email,phone,uid))
            except sqlite3.IntegrityError:return go('/painel/adotantes',req,'E-mail já cadastrado.',True)
        else:raise HTTPException(400,'Ação inválida')
        audit(c,actor['id'],'adotante_'+action,f'ID {uid}: {reason}')
    return go('/painel/adotantes',req,'Cadastro atualizado com histórico preservado.')

@app.get('/painel/equipe')
def staff_admin(req:Request):
    u=require_user(req,True)
    if u['role']!='admin':raise HTTPException(403,'Somente administradores gerenciam funcionários.')
    with db() as c:rows=[dict(x) for x in c.execute("SELECT id,name,email,phone,position,role,active,created_at FROM users WHERE role IN ('funcionario','admin') ORDER BY id DESC")]
    return page(req,'admin.html',kind='team',rows=rows,active='equipe')
@app.post('/painel/equipe')
async def staff_create(req:Request):
    u=require_user(req,True)
    if u['role']!='admin':raise HTTPException(403,'Somente administradores')
    f=await req.form();secure_form(req,f)
    name=clean(f.get('name'),130);email=clean(f.get('email'),160).lower();password=str(f.get('password') or '')
    cpf=digits(f.get('cpf'));phone=digits(f.get('phone'));position=clean(f.get('position'),120)
    if len(name)<4 or '@' not in email or len(password)<12 or not validate_cpf(cpf) or len(phone)<10 or not position:return go('/painel/equipe',req,'Preencha nome, CPF válido, telefone, função, e-mail e senha de 12 caracteres.',True)
    try:
        with db() as c:
            c.execute("INSERT INTO users(name,email,cpf,phone,position,password_hash,role,created_at) VALUES(?,?,?,?,?,?,'funcionario',?)",(name,email,cpf,phone,position,ph.hash(password),now()))
            audit(c,u['id'],'funcionario_criado',email)
    except sqlite3.IntegrityError:return go('/painel/equipe',req,'E-mail já cadastrado.',True)
    return go('/painel/equipe',req,'Funcionário cadastrado.')

@app.post('/painel/equipe/{uid}')
async def staff_update(req:Request,uid:int):
    actor=require_user(req,True)
    if actor['role']!='admin':raise HTTPException(403,'Somente administradores')
    f=await req.form();secure_form(req,f)
    action=clean(f.get('action'),20);reason=clean(f.get('reason'),500)
    with db() as c:
        target=c.execute("SELECT * FROM users WHERE id=? AND role IN ('funcionario','admin')",(uid,)).fetchone()
        if not target:raise HTTPException(404,'Funcionário inexistente')
        if action in ('inativar','ativar'):
            if uid==actor['id'] and action=='inativar':return go('/painel/equipe',req,'Não é possível inativar sua própria conta.',True)
            if action=='inativar' and len(reason)<10:return go('/painel/equipe',req,'Explique o motivo do desligamento/inativação.',True)
            if action=='inativar' and target['role']=='admin' and target['active']:
                count=c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
                if count<=1:return go('/painel/equipe',req,'É obrigatório manter pelo menos um administrador ativo.',True)
            c.execute('UPDATE users SET active=? WHERE id=?',(1 if action=='ativar' else 0,uid))
        elif action=='editar':
            name=clean(f.get('name'),140);phone=digits(f.get('phone'));position=clean(f.get('position'),130)
            if len(name)<4 or len(phone)<10 or not position:return go('/painel/equipe',req,'Confira nome, telefone e função.',True)
            c.execute('UPDATE users SET name=?,phone=?,position=? WHERE id=?',(name,phone,position,uid))
        else:raise HTTPException(400,'Ação não permitida')
        audit(c,actor['id'],'funcionario_'+action,f'ID {uid}: {reason}')
    return go('/painel/equipe',req,'Funcionário atualizado.')

@app.get('/painel/auditoria')
def audit_admin(req:Request):
    u=require_user(req,True)
    if u['role']!='admin':raise HTTPException(403,'Somente administradores')
    with db() as c:rows=[dict(x) for x in c.execute('SELECT a.*,u.name FROM audit a LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT 150')]
    return page(req,'admin.html',kind='audit',rows=rows,active='auditoria')

def cli():
    parser=argparse.ArgumentParser(description='SOS Patinhas')
    parser.add_argument('command',nargs='?',default='serve',choices=['serve','init','admin','demo'])
    parser.add_argument('--email');parser.add_argument('--name');parser.add_argument('--password');parser.add_argument('--port',type=int,default=8000)
    a=parser.parse_args();bootstrap()
    if a.command=='init':print('Banco inicializado:',DB);return
    if a.command=='admin':
        name=a.name or input('Nome do administrador: ').strip()
        email=(a.email or input('E-mail: ')).strip().lower()
        if a.password: pwd=a.password
        else:
            import getpass
            pwd=getpass.getpass('Senha (12+ caracteres): ')
        if len(pwd)<12 or not name or '@' not in email:raise SystemExit('Nome, e-mail e senha de no mínimo 12 caracteres são obrigatórios.')
        with db() as c:
            c.execute("INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,'admin',?)",(name,email,ph.hash(pwd),now()))
        print('Administrador criado.');return
    if a.command=='demo':
        # dados inteiramente fictícios para apresentação, sem dados pessoais
        with db() as c:
            if c.execute('SELECT COUNT(*) FROM animals').fetchone()[0]>0:
                print('Há animais cadastrados. Demonstração não sobrescrita.');return
            for n,s,breed,age,sex,size,descr,art in [
                ('Mel','Cão','SRD','2 anos','Fêmea','Médio','Carinhosa, sociável e adora passeios tranquilos.','dog-mel-photo.webp'),
                ('Bidu','Gato','SRD','8 meses','Macho','Pequeno','Curioso, brincalhão e acostumado com carinho.','cat-bidu-photo.webp'),
                ('Luna','Cão','SRD','1 ano','Fêmea','Médio','Companheira delicada que ama brincar ao ar livre.','dog-luna-photo.webp'),
                ('Thor','Cão','SRD','3 anos','Macho','Grande','Alegre, sociável e cheio de energia para aventuras.','dog-thor-photo.webp')]:
                ts=now()
                c.execute("INSERT INTO animals(name,species,breed,age,sex,size,description,health,status,neutered,vaccinated,dewormed,photo,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(n,s,breed,age,sex,size,descr,'Sem intercorrências informadas (demonstração)','Apto para adoção',1,1,1,'/static/img/'+art,ts,ts))
        print('Quatro animais fictícios de demonstração criados. Não são animais reais disponíveis para adoção.');return
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=a.port)

bootstrap()
if __name__=='__main__':cli()
