"""Functional tests with an isolated temporary database.
Run: python -m pytest -q tests/
"""
import importlib
import io
import os
import re
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from PIL import Image
import pytest

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))


def cpf_from(nine):
    d=list(map(int,nine))
    for end in (9,10):
        chk=(sum(d[i]*(end+1-i) for i in range(end))*10)%11
        d.append(0 if chk==10 else chk)
    return ''.join(map(str,d))

@pytest.fixture
def system(tmp_path,monkeypatch):
    monkeypatch.setenv('SOS_DB',str(tmp_path/'test.sqlite'))
    monkeypatch.setenv('SOS_SECRET_KEY','secure-test-key-which-is-long-enough')
    sys.modules.pop('app',None)
    mod=importlib.import_module('app')
    adopter=TestClient(mod.app)
    admin=TestClient(mod.app)
    with mod.db() as c:
        c.execute("INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,'admin',?)",('Admin Teste','admin@example.org',mod.ph.hash('senha-super-segura-123'),mod.now()))
    return mod,adopter,admin


def csrf(client,url='/'):
    response=client.get(url)
    assert response.status_code==200, response.text[:400]
    match=re.search(r'name="csrf"[^>]*value="([^"]+)"',response.text)
    assert match, f'CSRF missing: {url}'
    return match.group(1)


def signin(client,email,password):
    t=csrf(client,'/entrar')
    r=client.post('/entrar',data={'csrf':t,'ident':email,'password':password},follow_redirects=False)
    assert r.status_code==303, r.text[:200]
    return r


def test_public_pages_and_security(system):
    app,user,admin=system
    for url in ['/','/adotar','/denunciar','/cadastro','/entrar','/sobre','/ajudar','/voluntariado','/conteudos','/privacidade','/termos']:
        assert user.get(url).status_code==200
    assert user.get('/painel',follow_redirects=False).status_code==303
    assert user.post('/denunciar',data={'species':'Cão'}).status_code==403
    assert user.get('/painel/relatorios/denuncias.csv',follow_redirects=False).status_code==303
    assert user.get('/static/css/style.css').status_code==200
    assert user.get('/static/img/hero-dog-photo.webp').status_code==200


def test_complete_adoption_flow(system):
    mod,user,admin=system
    reg=user.post('/cadastro',data={
       'csrf':csrf(user,'/cadastro'),'name':'Pessoa de Teste','email':'pessoa@example.org',
       'cpf':cpf_from('123456789'),'phone':'14999999999','dob':'1990-01-01',
       'cep':'19900000','street':'Rua Teste','number':'123','district':'Centro',
       'city':'Ourinhos','uf':'SP','password':'senha-minima-123','confirm':'senha-minima-123','agree':'sim'},follow_redirects=False)
    assert reg.status_code==303 and reg.headers['location']=='/minha-conta',reg.headers
    assert user.get('/painel',follow_redirects=False).status_code==403
    assert signin(admin,'admin@example.org','senha-super-segura-123').headers['location']=='/painel'
    r=admin.post('/painel/resgates',data={'csrf':csrf(admin,'/painel/resgates'),'provisional_name':'Filhotinho','species':'Cão','sex':'Macho','size':'Pequeno','rescue_date':'2026-10-19','location':'Bairro Centro','initial_health':'Aparentemente saudável','behavior':'Dócil'},follow_redirects=False)
    assert r.status_code==303
    with mod.db() as c:
        rescue=c.execute('SELECT * FROM rescues LIMIT 1').fetchone()
        assert rescue and rescue['protocol'].startswith('RES-')
    im=Image.new('RGB',(200,180),(148,185,105));b=io.BytesIO();im.save(b,format='PNG')
    r=admin.post('/painel/animais',data={'csrf':csrf(admin,'/painel/animais'),'rescue_id':str(rescue['id']),'name':'Pipoca','species':'Cão','breed':'SRD','age':'1 ano','sex':'Macho','size':'Pequeno','description':'Um amigo brincalhão para sua família','health':'Vacinado e castrado','status':'Apto para adoção','neutered':'on','vaccinated':'on','dewormed':'on'},files={'photo':('pipoca.png',b.getvalue(),'image/png')},follow_redirects=False)
    assert r.status_code==303,r.text
    with mod.db() as c:
        animal=c.execute('SELECT * FROM animals WHERE name="Pipoca"').fetchone()
        assert animal, r.headers
        assert animal['status']=='Apto para adoção'
    aid=animal['id']
    assert user.get('/animal/'+str(aid)).status_code==200
    r=user.post(f'/adotar/{aid}/solicitar',data={'csrf':csrf(user,f'/adotar/{aid}/solicitar'),'household':'Casa com quintal cercado','experience':'Já cuidei de vários animais','motivation':'Quero oferecer uma vida feliz'},follow_redirects=False)
    assert r.status_code==303
    with mod.db() as c:
        adoption=c.execute('SELECT * FROM adoptions WHERE animal_id=?',(aid,)).fetchone()
        assert adoption
    rid=adoption['id']
    for action in ['iniciar','aprovar']:
        r=admin.post(f'/painel/solicitacoes/{rid}',data={'csrf':csrf(admin,'/painel/solicitacoes'),'action':action,'evaluation_notes':'A família foi entrevistada e considerada apta para a adoção.'},follow_redirects=False)
        assert r.status_code==303,r.text
    response=user.get('/minha-conta')
    assert 'Solicitação aprovada' in response.text
    assert admin.get(f'/painel/solicitacoes/{rid}/termo').content.startswith(b'%PDF-')
    pdf=b'%PDF-1.4\n%%EOF\n'  # Test accepts a PDF signature; production still requires authentic verification.
    r=admin.post(f'/painel/solicitacoes/{rid}',data={'csrf':csrf(admin,'/painel/solicitacoes'),'action':'concluir'},files={'signed_term':('termo.pdf',pdf,'application/pdf')},follow_redirects=False)
    assert r.status_code==303
    with mod.db() as c:
        animal=c.execute('SELECT status FROM animals WHERE id=?',(aid,)).fetchone()
        assert animal['status']=='Adotado'
        assert c.execute('SELECT COUNT(*) FROM followups WHERE adoption_id=?',(rid,)).fetchone()[0]==3
    assert user.get(f'/animal/{aid}').status_code==404
    assert admin.get('/painel/acompanhamentos').status_code==200
    assert user.get(f'/adocoes/{rid}/documento').status_code==200
    assert admin.get('/painel/relatorios/adocoes.csv').status_code==200
    assert admin.get('/painel/relatorios').status_code==200


def test_complaints_volunteering_donations(system):
    mod,user,admin=system
    r=user.post('/denunciar',data={'csrf':csrf(user,'/denunciar'),'species':'Cão','occurred_at':'2026-10-19T10:30','location':'Bairro Nosso Bairro','reference':'Praça','description':'Animal sozinho aparenta estar abandonado há vários dias','anonymous':'sim'},follow_redirects=False)
    assert r.status_code==200 and 'Denúncia registrada' in r.text
    with mod.db() as c:cid=c.execute('SELECT id FROM complaints').fetchone()[0]
    assert signin(admin,'admin@example.org','senha-super-segura-123').status_code==303
    assert admin.get('/painel/denuncias').status_code==200
    r=admin.post(f'/painel/denuncias/{cid}',data={'csrf':csrf(admin,'/painel/denuncias'),'status':'Em verificação'},follow_redirects=False)
    assert r.status_code==303
    r=admin.post('/painel/doacoes',data={'csrf':csrf(admin,'/painel/doacoes'),'kind':'Material','item':'Ração','quantity':'5','condition':'Nova','donor':'Anônimo','received_at':'2026-10-19'},follow_redirects=False)
    assert r.status_code==303
    assert admin.get('/painel/relatorios/doacoes.csv').status_code==200
    assert admin.get('/painel/doacoes/1/recibo').content.startswith(b'%PDF-')
    r=admin.post('/painel/campanhas',data={'csrf':csrf(admin,'/painel/campanhas'),'title':'Feira de adoção','description':'Evento de conscientização e acolhimento animal','type':'Evento'},follow_redirects=False)
    assert r.status_code==303
    assert 'Feira de adoção' in user.get('/').text

def test_privacy_intake_notifications_and_recovery(system):
    mod,user,admin=system
    assert user.get('/recuperar').status_code==200
    rr=user.post('/recuperar',data={'csrf':csrf(user,'/recuperar'),'email':'teste@example.org'})
    assert rr.status_code==200 and 'Recuperação indisponível' in rr.text
    assert user.get('/entregar-animal',follow_redirects=False).status_code==303
    data={
       'csrf':csrf(user,'/cadastro'),'name':'Pessoa Teste LGPD','email':'privacidade@example.org',
       'cpf':cpf_from('347821906'),'phone':'14999995555','dob':'1989-05-11',
       'cep':'19900000','street':'Rua A','number':'23','district':'Centro',
       'city':'Ourinhos','uf':'SP','password':'senha-minima-123','confirm':'senha-minima-123','agree':'sim'}
    assert user.post('/cadastro',data=data,follow_redirects=False).status_code==303
    response=user.get('/minha-conta/exportar')
    assert response.status_code==200
    assert 'password_hash' not in response.text
    assert 'privacidade@example.org' in response.text
    r=user.post('/minha-conta/exclusao',data={'csrf':csrf(user,'/minha-conta'),'password':'senha-minima-123'},follow_redirects=False)
    assert r.status_code==303
    r=user.post('/entregar-animal',data={'csrf':csrf(user,'/entregar-animal'),'species':'Gato','age':'2 anos','location':'Ourinhos Centro','condition':'Saudável, mas sem abrigo adequado','reason':'Não tenho condições de mantê-lo'},follow_redirects=False)
    assert r.status_code==303
    assert signin(admin,'admin@example.org','senha-super-segura-123').status_code==303
    assert admin.get('/painel/privacidade').status_code==200
    assert admin.get('/painel/acolhimentos').status_code==200
    assert admin.post('/painel/mensagens',data={'csrf':csrf(admin,'/painel/mensagens'),'title':'Aviso para adotantes','message':'Lembre-se de cuidar bem das patinhas!','target':'adotantes'},follow_redirects=False).status_code==303
    assert 'Aviso para adotantes' in user.get('/minha-conta').text
    with mod.db() as c:
        pid=c.execute('SELECT id FROM privacy_requests').fetchone()[0]
        iid=c.execute('SELECT id FROM intakes').fetchone()[0]
    assert admin.post(f'/painel/privacidade/{pid}',data={'csrf':csrf(admin,'/painel/privacidade'),'status':'Em análise'},follow_redirects=False).status_code==303
    assert admin.post(f'/painel/acolhimentos/{iid}',data={'csrf':csrf(admin,'/painel/acolhimentos'),'status':'Aprovado para contato'},follow_redirects=False).status_code==303


def test_adoption_queue_blocks_out_of_order_approval(system):
    mod,u1,admin=system
    u2=TestClient(mod.app)
    # Two accounts in order
    for idx,client in [(1,u1),(2,u2)]:
        r=client.post('/cadastro',data={'csrf':csrf(client,'/cadastro'),'name':f'Pessoa Teste {idx}',
           'email':f'pessoa{idx}@example.org','cpf':cpf_from('19876543'+str(idx)),'phone':'14999999999',
           'dob':'1990-01-01','cep':'19900000','street':'Rua Teste','number':'123','district':'Centro',
           'city':'Ourinhos','uf':'SP','password':'senha-minima-123','confirm':'senha-minima-123','agree':'sim'},follow_redirects=False)
        assert r.status_code==303
    with mod.db() as c:
        c.execute("INSERT INTO animals(name,species,breed,age,sex,size,health,status,neutered,photo,created_at,updated_at) VALUES('Nina','Gato','SRD','1 ano','Fêmea','Pequeno','Ok','Apto para adoção',1,'/static/img/cat-bidu-photo.webp',?,?)",(mod.now(),mod.now()))
        aid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
    for client in (u1,u2):
        assert client.post(f'/adotar/{aid}/solicitar',data={'csrf':csrf(client,f'/adotar/{aid}/solicitar'),'household':'Tenho quintal cercado','experience':'Criei outros animais antes','motivation':'Tenho muito amor para oferecer'},follow_redirects=False).status_code==303
    with mod.db() as c:
        ids=[x['id'] for x in c.execute('SELECT id FROM adoptions ORDER BY id')]
    assert signin(admin,'admin@example.org','senha-super-segura-123').status_code==303
    admin.post(f'/painel/solicitacoes/{ids[0]}',data={'csrf':csrf(admin,'/painel/solicitacoes'),'action':'iniciar'})
    admin.post(f'/painel/solicitacoes/{ids[1]}',data={'csrf':csrf(admin,'/painel/solicitacoes'),'action':'aprovar'})
    with mod.db() as c:
        assert c.execute('SELECT status FROM adoptions WHERE id=?',(ids[1],)).fetchone()['status']=='Em análise'
        assert c.execute('SELECT in_review FROM adoptions WHERE id=?',(ids[0],)).fetchone()['in_review']==1


def test_admin_account_and_logout_controls(system):
    mod,user,admin=system
    assert signin(admin,'admin@example.org','senha-super-segura-123').status_code==303
    panel=admin.get('/painel')
    assert panel.status_code==200
    assert 'href="/minha-conta"' in panel.text
    assert 'Sair da conta' in panel.text
    assert 'action="/sair"' in panel.text
    account=admin.get('/minha-conta')
    assert account.status_code==200
    assert 'Voltar ao painel administrativo' in account.text
    assert admin.post('/sair',data={'csrf':csrf(admin,'/painel')},follow_redirects=False).status_code==303
    assert admin.get('/painel',follow_redirects=False).status_code==303
