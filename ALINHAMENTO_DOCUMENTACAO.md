# Divergências e decisões sobre o documento de requisitos

Este arquivo **não altera** o trabalho escrito: documenta decisões de implementação que o grupo precisa revisar com o professor/orientador.

## Conflitos encontrados na especificação

1. **RF03 — Exclusão de denúncias:** o item 3.6 informa que o denunciante não pode alterar ou excluir a denúncia; o item 3.9 permite sua exclusão se ainda estiver em status `Recebida`. O sistema privilegia preservação da denúncia e acesso de equipe, **sem permitir exclusão pelo denunciante**. O grupo deve definir oficialmente a regra.
2. **RF13/RF16 — Relatórios:** o quadro-resumo da seção 3.1 nomeia RF13 como doações e RF16 como animais resgatados; trechos detalhados posteriores trocam seus nomes ou misturam seus campos. Foram criados módulos temáticos de relatório independentes, com exportação CSV/XLSX/PDF. Corrigir a matriz de rastreabilidade depois que a nomenclatura estiver aprovada.
3. **RF02 — Senha:** documento menciona mínimo de seis caracteres; o site exige 10 caracteres para adotantes e 12 para equipe. É uma regra mais forte, que deve ser documentada como decisão de segurança.
4. **RF05 — Castração:** apenas animais com castração registrada ficam aptos a adoção. A exceção de demo cria registros fictícios já cadastrados, sem relatório inicial, para apresentação; não representa o fluxo operacional.
5. **RF11 versus escopo (seção 1.3):** a intermediação financeira está excluída, mas registrar doações é obrigatório. A página Pix oferece uma forma de consulta a dados bancários configurados, sem processar ou intermediar a transação. Formalizar no escopo como recurso informativo opcional.

## Pontos para futura entrega completa

- Editor mais amplo de adotantes (endereço completo, CPF controlado e registros de alteração).
- Relatórios detalhados de pós-adoção, evolução geográfica de denúncias, tempos médios e indicadores epidemiológicos quando autorizados.
- Gestão de documentos da avaliação com controle de retenção e assinatura certificada, se exigida.
- Notificações SMS/e-mail/push, agendamento de tarefas em segundo plano e política de falha/reenvio.
- Despesas/vencimentos para os alertas previstos no RF12; atualmente esse módulo não está implementado.
- Revisão institucional de proteção de dados, direitos e consentimentos; testes de carga para RNF01–RNF03.

## Segurança operacional

Nenhuma chave Pix ou contato bancário de exemplo deve ser disponibilizado como oficial. Use apenas dados verificados pela entidade e teste o QR Code estático num aplicativo bancário da entidade antes de divulgá-lo. O serviço da ONG precisa existir de fato para receber denúncias/adoções reais. Não divulgue fotografias e dados pessoais sem autorização e sem base legal apropriada.
