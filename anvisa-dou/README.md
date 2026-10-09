# Anvisa no DOU: suspensões e aprovações

Painel que se atualiza sozinho nos dias úteis com os atos publicados no Diário Oficial da União (Seção 1) por:

- **4ª Diretoria / Gerência-Geral de Inspeção e Fiscalização Sanitária (GGFIS)**: suspensões, proibições, recolhimentos e interdições de produtos.
- **2ª Diretoria / Gerência-Geral de Medicamentos (GGMED)**: registros e aprovações de medicamentos.

## Como funciona

```
GitHub Actions (08h e 14h, seg a sex)
   └─ scripts/coletar.py baixa a edição do dia no INLABS (XML)
        └─ filtra os atos dessas duas unidades da Anvisa
             └─ grava docs/dados.json e docs/feed.xml
                  └─ GitHub Pages publica docs/index.html
```

## Passo a passo (cerca de 10 minutos)

1. **Cadastre-se no INLABS** (gratuito): https://inlabs.in.gov.br
2. **Crie um repositório** no GitHub e envie todo o conteúdo desta pasta.
3. Em **Settings > Secrets and variables > Actions**, crie dois secrets:
   - `INLABS_EMAIL`: e-mail do cadastro no INLABS
   - `INLABS_SENHA`: senha do INLABS
4. Em **Settings > Pages**, escolha *Deploy from a branch*, branch `main`, pasta `/docs`.
5. Em **Actions > Atualizar publicações do DOU > Run workflow**, informe `30` em "dias" para o primeiro preenchimento. O INLABS guarda um histórico limitado, então períodos muito antigos podem não estar disponíveis.
6. Pronto. O painel fica em `https://SEU-USUARIO.github.io/NOME-DO-REPOSITORIO/` e o feed RSS em `.../feed.xml`.

## Ajustes

Tudo fica no topo de `scripts/coletar.py`:

- `UNIDADES`: trechos do nome do órgão usados para reconhecer cada unidade. Se a Anvisa mudar a numeração das diretorias, altere aqui.
- `RE_SUSPENSAO`, `RE_APROVACAO`, `RE_NEGATIVA`: palavras que separam suspensão, aprovação e outros atos.
- `RETENCAO_DIAS`: quanto histórico manter (padrão: 180 dias).

## Pontos de atenção

- **Teste com dados reais antes de confiar.** A leitura do XML e a classificação foram testadas apenas com exemplos sintéticos. Rode o workflow uma vez, confira alguns atos no painel contra o DOU e ajuste as regras se necessário.
- **A classificação é por palavras-chave.** Um ato de suspensão sem essas palavras, ou um ato de medicamento que mencione "cancelamento" ao lado de um registro, pode cair em "Outros atos". Por isso a aba existe: nada é descartado.
- **Credenciais do INLABS**: o acesso é pessoal. Mantenha os secrets só no GitHub, nunca no código.
- **Inatividade**: o GitHub desativa workflows agendados em repositórios sem nenhuma atividade por 60 dias. Se o painel parar, reative o workflow na aba Actions.
- O painel é um apoio de consulta. Para fins legais ou regulatórios, confira sempre o ato no DOU.
