# SOS Patinhas — Matriz de implementação dos requisitos

Base: **SOS Patinhas atualizado.docx**, seção 3.1 (RF01–RF16), seção 3.2 (RNF01–RNF12) e escopo da seção 1.3. Estado: versão acadêmica revisada em outubro de 2026.

**Legenda:** `Implementado` = fluxo principal existente e testado; `Parcial` = implementado apenas em parte; `Pendente` = não implementado. A marca `Implementado` **não** significa homologação para operação real, nem cobertura de todas as subcláusulas do requisito.

## Requisitos funcionais

| ID | Documento | O que o site entrega hoje | Situação |
|---|---|---|---|
| RF01 | Cadastrar funcionário | Administrador cadastra CPF/e-mail/função/telefone, edita nome/cargo/telefone, ativa/inativa com motivo e auditoria; não há exclusão física, e o cadastro inicial via CLI não exige CPF | Parcial |
| RF02 | Efetuar login | Autenticação por CPF ou e-mail, perfis de equipe e adotante, bloqueio após 3 falhas em 15 min, troca de senha; recuperação por e-mail depende de SMTP | Parcial |
| RF03 | Registrar denúncia | Anônima ou identificada, data/local/espécie, evidência privada, protocolo, status administrativo; exclusão pelo denunciante não disponível por conflito do documento | Parcial |
| RF04 | Relatório inicial de resgate | Protocolo, campos exigidos, foto/PDF opcional privado, cadastro imutável | Implementado |
| RF05 | Cadastro definitivo de animal | Vinculado ao resgate, estado de saúde, foto principal e extras, status regrados, justificativas e histórico das alterações; modo `demo` é exceção explícita | Parcial |
| RF06 | Cadastrar adotante | Registro com CPF único e endereço, histórico de adoções, edição básica, restrição justificada e inativação lógica pela equipe; falta edição completa de endereço/CPF | Parcial |
| RF07 | Solicitar adoção e fila | Solicitação com data/hora, ordem de chegada, triagem exclusiva, bloqueio de pedidos durante triagem, desistência e próximo da fila | Implementado |
| RF08 | Avaliar candidato | Iniciar triagem, parecer obrigatório na aprovação, recusa justificada e anexo privado; ainda não há roteiro completo parametrizável de entrevista | Parcial |
| RF09 | Gerar termo de adoção | PDF com dados, upload do termo assinado e status 'Adotado' após registro; não implementa assinatura eletrônica certificada | Parcial |
| RF10 | Pós-adoção | Agendamentos 15/90/180 dias, registro de contato, fotos privadas, reagendamento e alertas no painel; relatório específico consolidado é limitado | Parcial |
| RF11 | Gerenciar doações | Doação material/financeira registrada, recibo simples PDF, resumo por doador, página pública Pix sem intermediação; sem validação bancária automática | Parcial |
| RF12 | Enviar notificações | Mensagens internas, comunicados em massa e avisos de vacinação/acompanhamento ao abrir painel; sem canais SMS/push/e-mail automáticos ou anexos em avisos | Parcial |
| RF13 | Relatórios: títulos conflitantes | Exportação de animais/resgates/doações; indicadores e alguns gráficos; campos/gráficos específicos não todos | Parcial |
| RF14 | Relatório de adoções | Totais, gráfico mensal, CSV/XLSX/PDF e filtros; falta tempo médio de adoção e análises mais completas por espécie | Parcial |
| RF15 | Relatório de denúncias | Consolidação por status, exportação CSV/XLSX/PDF, filtros por período/espécie/situação; falta mapa de calor e tempo médio até conclusão | Parcial |
| RF16 | Relatórios: títulos conflitantes | Dados e exportações de doações, resgates e animais; falta o conjunto integral de indicadores e gráficos solicitados | Parcial |

**Observação:** RF13/RF16 têm rótulos diferentes entre o resumo e o detalhamento do documento. O sistema mantém relatórios separados por tema, sem afirmar que a numeração foi resolvida. Ver `ALINHAMENTO_DOCUMENTACAO.md`.

## Requisitos não funcionais

| ID | Especificação | Estado real |
|---|---|---|
| RNF01 | Página inicial e funcionalidades em até 3 s | Não homologado com teste de carga e rede de 5 Mbps; assets WebP otimizados |
| RNF02 | Busca em até 3 s | Busca funcional, ainda sem medição formal em todos os cenários |
| RNF03 | Disponibilidade de 99,9% | Não comprovado; desenvolvimento local não tem SLA |
| RNF04 | Chrome, Firefox, Edge e Safari | HTML responsivo; testes sistemáticos das duas últimas versões pendentes |
| RNF05 | Desktop, tablet e celular | Layout responsivo por CSS; testes automatizados de interface multiplataforma pendentes |
| RNF06 | Troca e recuperação de senha | Troca concluída; recuperação por e-mail depende de SMTP |
| RNF07 | Erros amigáveis | Mensagens de erro e confirmação nos formulários |
| RNF08 | Senhas seguras | Hash Argon2 no banco |
| RNF09 | Validação de entradas | Validações servidor/cliente, queries SQL parametrizadas e escaping Jinja; revisão de segurança pendente |
| RNF10 | Logs de ações críticas | Auditoria de cadastros, acesso e operações da equipe |
| RNF11 | LGPD | Exportar dados e pedir exclusão, restrição de acesso; processo institucional de exclusão ainda manual |
| RNF12 | Manutenibilidade | Backend FastAPI, templates, CSS/JS, documentação e testes; refatoração em módulos separados ainda é recomendada |

## Outras funcionalidades ligadas ao escopo

- Divulgação de campanhas e eventos: **implementado fluxo básico** (publicar e ocultar).
- Voluntariado: formulário, aprovação, atividades internas autorizadas: **implementado fluxo básico**.
- Divulgação de clínicas e pet shops parceiros: **implementado fluxo básico**; somente a equipe publica.
- Acolhimento/doação de animais: formulário e análise de pedido: **implementado fluxo básico**, sem aceite automático.
- Doação financeira por Pix: **adicional**; página meramente informativa que requer configuração de dados oficiais e permite QR Code estático quando nome/cidade/chave estão disponíveis; não processa pagamento.
- Fotos da demonstração: arquivos WebP otimizados. **São imagens geradas por IA**, não animais reais da ONG.

## Recursos ainda não concluídos / fora do escopo

- Assinatura eletrônica com validação criptográfica ou certificação.
- SMS, notificações push e alertas independentes de abertura do painel.
- Exportações analíticas com todos os gráficos, médias e recortes do documento.
- Gestão de múltiplas ONGs, atendimento veterinário remoto e geolocalização em tempo real (expressamente fora do escopo inicial).
- Processamento financeiro, checkout, conciliação Pix, emissão de nota fiscal.
- Implantação em produção, SLA, segurança auditada, avaliação jurídica completa/LGPD.

## Ensaios

Há testes automatizados para fluxos de acesso, adoção, resgate, cadastro de animais, denúncias, doações, parceiros, funcionários, Pix e relatórios. Estes testes **não substituem** homologação completa, análise de segurança ou testes de usabilidade.
