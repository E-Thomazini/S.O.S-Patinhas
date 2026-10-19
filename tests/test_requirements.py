"""Tests additional requirements and private areas on a separate temporary database."""
import io
from PIL import Image
from test_workflow import system,csrf,signin


def login_admin(cl):
    assert signin(cl,'admin@example.org','senha-super-segura-123').status_code==303


def test_donations_unconfigured_and_configured(system,monkeypatch):
    mod,user,admin=system
    monkeypatch.delenv('SOS_DONATION_PIX_KEY',raising=False)
    content=user.get('/ajudar').text
    assert 'não habilitadas' in content
    assert 'pix@sospatinhas.org.br' not in content
    monkeypatch.setenv('SOS_DONATION_PIX_KEY','chave.teste@exemplo.org')
    content=user.get('/ajudar').text
    assert 'chave.teste@exemplo.org' in content
    assert 'data-copy-target' in content
    assert 'R$ 10' in content and 'R$ 25' in content and 'R$ 50' in content
    monkeypatch.setenv('SOS_DONATION_PIX_NAME','ONG EXEMPLO')
    monkeypatch.setenv('SOS_DONATION_PIX_CITY','OURINHOS')
    qr=user.get('/ajudar/pix.png')
    assert qr.status_code==200 and qr.headers['content-type']=='image/png' and qr.content.startswith(b'\x89PNG')


def test_new_pages_and_access_control(system):
    mod,user,admin=system
    assert user.get('/parceiros').status_code==200
    assert user.get('/voluntariado/atividades',follow_redirects=False).status_code==303
    for url in ['/painel/parceiros','/painel/atividades','/painel/adotantes']:
        assert user.get(url,follow_redirects=False).status_code==303
    login_admin(admin)
    for url in ['/painel/parceiros','/painel/atividades','/painel/adotantes','/painel/equipe']:
        assert admin.get(url).status_code==200, url
    assert admin.post('/painel/parceiros',data={'csrf':csrf(admin,'/painel/parceiros'),'name':'Clínica Modelo','category':'Veterinária','description':'Apoia cuidados dos animais'},follow_redirects=False).status_code==303
    assert 'Clínica Modelo' in user.get('/parceiros').text
    assert admin.post('/painel/atividades',data={'csrf':csrf(admin,'/painel/atividades'),'title':'Campanha de arrecadação','description':'Organizar itens para a próxima campanha.'},follow_redirects=False).status_code==303
    assert admin.get('/voluntariado/atividades').status_code==200


def test_staff_and_adopter_management(system):
    mod,user,admin=system
    login_admin(admin)
    with mod.db() as c:
        c.execute("INSERT INTO users(name,email,phone,password_hash,role,created_at) VALUES(?,?,?,?,?,?)",('Pessoa Exemplo','pessoa@exemplo.org','14999999999',mod.ph.hash('senha-pessoa-forte'),'adotante',mod.now()))
        uid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        c.execute("INSERT INTO users(name,email,phone,position,password_hash,role,created_at) VALUES(?,?,?,?,?,?,?)",('Funcionário Teste','func@exemplo.org','14999999999','Apoio',mod.ph.hash('senha-pessoa-forte'),'funcionario',mod.now()))
        fid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        aid=c.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
    token=csrf(admin,'/painel/adotantes')
    assert admin.post(f'/painel/adotantes/{uid}',data={'csrf':token,'action':'restringir','reason':'Necessário confirmar informações cadastrais'},follow_redirects=False).status_code==303
    with mod.db() as c:
        assert c.execute('SELECT restricted_reason FROM users WHERE id=?',(uid,)).fetchone()[0]
    token=csrf(admin,'/painel/equipe')
    assert admin.post(f'/painel/equipe/{fid}',data={'csrf':token,'action':'inativar','reason':'Encerramento do contrato com a equipe'},follow_redirects=False).status_code==303
    assert admin.post(f'/painel/equipe/{aid}',data={'csrf':token,'action':'inativar','reason':'Teste de próprio desligamento'},follow_redirects=False).status_code==303
    with mod.db() as c:
        assert c.execute('SELECT active FROM users WHERE id=?',(aid,)).fetchone()[0]==1
        assert c.execute('SELECT active FROM users WHERE id=?',(fid,)).fetchone()[0]==0


def test_reports_filters_and_formats(system):
    mod,user,admin=system
    login_admin(admin)
    with mod.db() as c:
        c.execute('INSERT INTO donations(kind,amount,donor,method,received_at,recorded_by) VALUES(?,?,?,?,?,?)',('Financeira',25,'Ana','Pix','2026-10-10',1))
        c.execute('INSERT INTO donations(kind,amount,donor,method,received_at,recorded_by) VALUES(?,?,?,?,?,?)',('Financeira',50,'Carlos','Dinheiro','2026-10-18',1))
    assert 'Ana' in admin.get('/painel/doacoes').text
    response=admin.get('/painel/relatorios/doacoes.csv?inicio=2026-10-15&fim=2026-10-20')
    assert response.status_code==200
    assert 'Carlos' in response.text and 'Ana' not in response.text
    response=admin.get('/painel/relatorios/doacoes.xlsx')
    assert response.status_code==200 and response.content[:2]==b'PK'
    response=admin.get('/painel/relatorios/doacoes.pdf')
    assert response.status_code==200 and response.content.startswith(b'%PDF-')
    assert admin.get('/painel/relatorios/doacoes.csv?inicio=invalido').status_code==400


def test_rescue_photo_and_animal_history(system):
    mod,user,admin=system
    login_admin(admin)
    b=io.BytesIO();Image.new('RGB',(80,80),'brown').save(b,format='PNG');photo=b.getvalue()
    r=admin.post('/painel/resgates',data={'csrf':csrf(admin,'/painel/resgates'),'provisional_name':'Provisório','species':'Cão','sex':'Macho','size':'Pequeno','rescue_date':'2026-10-19','location':'Área central de Ourinhos','initial_health':'Condição inicial aparentemente estável'},files={'photo':('rescue.png',photo,'image/png')},follow_redirects=False)
    assert r.status_code==303
    with mod.db() as c:rid=c.execute('SELECT id FROM rescues').fetchone()[0]
    assert user.get(f'/painel/resgates/{rid}/foto',follow_redirects=False).status_code==303
    assert admin.get(f'/painel/resgates/{rid}/foto').status_code==200
    fields={'csrf':csrf(admin,'/painel/animais'),'rescue_id':rid,'name':'Sol','species':'Cão','breed':'SRD','age':'2 anos','sex':'Macho','size':'Pequeno','description':'Muito gentil','health':'Sem sinais aparentes','status':'Apto para adoção','neutered':'on','vaccination_due':'2026-10-25'}
    r=admin.post('/painel/animais',data=fields,files=[('photo',('foto.png',photo,'image/png')),('more_photos',('extra.png',photo,'image/png'))],follow_redirects=False)
    assert r.status_code==303
    with mod.db() as c:
        aid=c.execute('SELECT id FROM animals WHERE name="Sol"').fetchone()[0]
        assert c.execute('SELECT COUNT(*) FROM animal_photos WHERE animal_id=?',(aid,)).fetchone()[0]==1
    assert 'Foto adicional de Sol' in user.get(f'/animal/{aid}').text
    r=admin.post('/painel/animais',data={**fields,'csrf':csrf(admin,'/painel/animais?editar='+str(aid)),'id':aid,'name':'Solzinho'},follow_redirects=False)
    assert r.status_code==303
    with mod.db() as c:
        assert c.execute('SELECT COUNT(*) FROM animal_edits WHERE animal_id=?',(aid,)).fetchone()[0]>0
    assert admin.get('/painel').status_code==200
    assert 'Vacinação próxima' in admin.get('/minha-conta').text

def test_withdrawal_moves_waiting_queue(system):
    mod,user,admin=system
    with mod.db() as c:
        c.execute("INSERT INTO animals(name,species,breed,age,sex,size,health,status,neutered,created_at,updated_at) VALUES('Pipoca','Cão','SRD','2 anos','Fêmea','Médio','Castrada','Apto para adoção',1,?,?)",(mod.now(),mod.now()))
        animal=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        for i in range(2):
            c.execute("INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,'adotante',?)",(f'Adotante {i}',f'adotante{i}@example.org',mod.ph.hash('senha-segura-456'),mod.now()))
            uid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
            c.execute('INSERT INTO adoptions(animal_id,user_id,household,experience,motivation,created_at) VALUES(?,?,?,?,?,?)',(animal,uid,'Apartamento seguro','Já tive cães','Quero adotar',f'2026-10-19T12:0{i}:00'))
        rid=c.execute('SELECT id FROM adoptions ORDER BY created_at LIMIT 1').fetchone()[0]
    login_admin(admin)
    assert admin.post(f'/painel/solicitacoes/{rid}',data={'csrf':csrf(admin,'/painel/solicitacoes'),'action':'iniciar'},follow_redirects=False).status_code==303
    assert signin(user,'adotante0@example.org','senha-segura-456').status_code==303
    assert user.post(f'/minha-conta/solicitacoes/{rid}/desistir',data={'csrf':csrf(user,'/minha-conta')},follow_redirects=False).status_code==303
    with mod.db() as c:
        assert c.execute('SELECT status FROM adoptions WHERE id=?',(rid,)).fetchone()[0]=='Desistiu'
        assert c.execute('SELECT status FROM animals WHERE id=?',(animal,)).fetchone()[0]=='Apto para adoção'
        assert c.execute('SELECT COUNT(*) FROM notifications WHERE title="Próximo na fila"').fetchone()[0]==1
