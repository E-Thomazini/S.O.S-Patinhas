# 🐾 SOS Patinhas — Plataforma Web de Proteção Animal

Projeto acadêmico da disciplina de Engenharia de Software (FATEC Ourinhos, 2026), implementado em **Python 3 + FastAPI + Jinja2 + SQLite + JavaScript**.

**Finalidade:** apoiar a organização de denúncias, resgates, animais, triagens, adoções, doações, acompanhamento pós-adoção, voluntariado e campanhas. **É um protótipo acadêmico local**, não uma organização ou serviço público de emergência. Não o use para dados pessoais ou denúncias reais sem a revisão necessária.

## Executar no Zorin OS / Ubuntu / Mint

No terminal, dentro da pasta do projeto:

```bash
sudo apt install -y python3 python3-pip python3-venv
bash iniciar.sh demo   # opcional: cria 4 animais FICTÍCIOS se ainda não houver animais
bash iniciar.sh admin  # crie seu administrador com e-mail/senha próprios
bash iniciar.sh        # executa o site
```

Acesse **http://127.0.0.1:8000**. O script `iniciar.sh` instala as dependências em uma `.venv` isolada, sem usar `pip` no Python global (evita o erro `externally-managed-environment`/PEP 668). Não precisa de XAMPP. Para parar, pressione `Ctrl+C`.

Para entrar na administração, faça login com o administrador que você criou. Use **Minha conta** ou **Sair da conta** no menu lateral.

## Funcionalidades

| Área | Rotas principais |
|---|---|
| Página inicial, adoção e perfil | `/`, `/adotar`, `/animal/{id}` |
| Conta, registro, login e privacidade | `/cadastro`, `/entrar`, `/minha-conta` |
| Denúncias e solicitação de acolhimento | `/denunciar`, `/entregar-animal` |
| Doações e voluntariado | `/ajudar`, `/voluntariado`, `/voluntariado/atividades` |
| Parceiros e conteúdos | `/parceiros`, `/conteudos`, `/sobre` |
| Painel da ONG | `/painel` |
| Equipe, adotantes, animais e resgates | `/painel/equipe`, `/painel/adotantes`, `/painel/animais`, `/painel/resgates` |
| Adoções, denúncias e acompanhamento | `/painel/solicitacoes`, `/painel/denuncias`, `/painel/acompanhamentos` |
| Doações, parceiros, campanhas e voluntários | `/painel/doacoes`, `/painel/parceiros`, `/painel/campanhas`, `/painel/voluntarios`, `/painel/atividades` |
| Relatórios, mensagens e auditoria | `/painel/relatorios`, `/painel/mensagens`, `/painel/auditoria` |

A página de relatórios exporta **CSV, XLSX e PDF**, com filtros por período, espécie e situação (quando disponíveis). Há modelos de termo e recibo em PDF. O termo assinado pode ser enviado posteriormente como PDF: **não há assinatura eletrônica certificada ou validação criptográfica integrada**.

Para o quadro detalhado dos 16 requisitos funcionais e 12 não funcionais, leia **[FUNCIONALIDADES.md](FUNCIONALIDADES.md)**. O arquivo **[ALINHAMENTO_DOCUMENTACAO.md](ALINHAMENTO_DOCUMENTACAO.md)** registra diferenças e decisões pendentes.

## Doações Pix

A página **/ajudar** exibe doações materiais, voluntariado e contribuições financeiras por transferência Pix **fora do site**. Por segurança, nenhuma chave ou contato fictício é publicado. Configure o `.env` com **dados oficiais confirmados pela ONG**:

```bash
export SOS_DONATION_PIX_KEY=""
export SOS_DONATION_PIX_TYPE="E-mail"
export SOS_DONATION_PIX_NAME=""
export SOS_DONATION_PIX_CITY=""
export SOS_DONATION_RECEIPT=""
export SOS_DONATION_QR_IMAGE=""
```

Preencha os campos necessários. A chave só aparece quando `SOS_DONATION_PIX_KEY` estiver preenchida. Um QR Code Pix estático pode ser gerado quando **chave, nome e cidade oficiais** estão preenchidos. Também é possível apontar `SOS_DONATION_QR_IMAGE` para uma imagem oficial hospedada em `/static/img/` (por exemplo `/static/img/qr-oficial.png`). **Valide qualquer QR gerado com o aplicativo bancário da ONG antes de tornar a página pública.** Não há processamento, cobrança, conciliação bancária ou confirmação automática de pagamento.

Para outras configurações, consulte `.env.example`. Não compartilhe chaves de sessão/SMTP no GitHub.

## Atualizar sem perder o banco

1. Feche o servidor (`Ctrl+C`).
2. **Faça backup** de `sos_patinhas.db`, da pasta `static/uploads/`, da pasta `private/` e do `.env`.
3. Extraia a nova versão por cima da pasta anterior, substituindo arquivos de código (sem apagar suas pastas de dados).
4. Execute `bash iniciar.sh`. A aplicação aplica migrações incrementais aditivas no SQLite ao iniciar.
5. Confira o painel, seus arquivos privados, as fotos de animais e relatórios.

Se tiver uma `.venv` antiga com problema, o script guarda o ambiente antigo antes de recriar outro. Não é necessário apagar o banco.

## Fotos e demonstração

As seis imagens fotográficas da interface são **imagens fotorrealistas geradas por IA**, apenas demonstrativas; não representam resgates reais. Os animais Mel, Bidu, Luna e Thor criados pelo comando `demo` são fictícios. Para animais verdadeiros cadastrados pela equipe, o sistema aceita fotos próprias JPG, PNG e WebP e associa um relatório de resgate inicial. Referências antigas dos quatro SVGs de demonstração são convertidas para WebP na abertura do banco, sem sobrescrever fotos enviadas por usuários.

## Segurança e limites

- Senhas com hash Argon2, CSRF em formulários, separação de permissões e registros de auditoria.
- Evidências e documentos assinados ficam em `private/`, acessíveis por rotas autenticadas e autorizadas.
- As solicitações de adoção respeitam a fila e permitem desistência antes da aprovação. O cadastro do animal exige resgate inicial no fluxo operacional (exceto animais fictícios de demo).
- Alertas **internos** para vacina e acompanhamento são criados quando o painel administrativo é aberto. Não existe serviço agendador funcionando independentemente do painel ou notificação por SMS/push.
- Recuperação de senha por e-mail depende de SMTP configurado. O site não declara disponibilidade de 99,9% ou desempenho garantido sem testes de produção.
- Termos e políticas de privacidade são material acadêmico, não aconselhamento jurídico. Avalie LGPD, consentimento, retenção, autoridade institucional, HTTPS, backups, MFA e testes antes de qualquer implantação.

## Testes

```bash
.venv/bin/python -m pip install pytest httpx
.venv/bin/python -m pytest -q
```

Os testes usam bancos temporários para proteger os cadastros locais. São testados fluxos de adoção, denúncias, autorização, Pix configurável, uploads e relatórios.

## Publicar código no GitHub

O projeto contém `.gitignore` para não publicar `.env`, banco local, arquivos privados ou uploads. Confira os arquivos antes de enviar:

```bash
git init
git add .
git status --short
git commit -m "SOS Patinhas: alinhamento aos requisitos"
```

Adicione depois o remoto do seu repositório e faça o push. **Não suba uma versão com dados pessoais, denunciações, PDFs assinados ou credenciais reais.**
