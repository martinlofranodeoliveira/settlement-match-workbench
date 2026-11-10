# Settlement Match Workbench

Pacote Python e CLI local para explicar atribuições1:1 entre lotes sintéticos
e registros de crédito declarados. Primeiro maximiza a quantidade de pares;
depois minimiza o custo explícito de preferência por referência e data. Para
todos os ótimos, distingue arestas obrigatórias, opcionais e globalmente
excluídas, além de informar se cada registro pode ficar sem par.

[English](../README.md) · [Contrato da CLI](CLI-IO.md) · [Proveniência](../ORIGIN.md)

O representante é ilustrativo. `FORCED` expressa uma propriedade das entradas e
da política; não confirma pagamento bancário. O modelo usa
`líquido = bruto - taxas - reembolsos`, sem FX, reservas, disputas ou divisão de
payout. Valores monetários no JSON são strings decimais exatas, inclusive
agregados de17dígitos; moedas diferentes têm totais separados. O digest
identifica entradas normalizadas e não autentica sua origem.

## Executar

Com Docker e Python3 no host:

```sh
sh scripts/check.sh prepare
sh scripts/check.sh test
sh scripts/check.sh demo
```

A preparação usa uma imagem oficial fixada e três wheels oficiais com SHA256.
A execução seguinte é offline, sem bind do host, UID1000, capabilities removidas,
1GiB e2CPUs. O gate constrói SDist/wheel genuínos, reconstrói o wheel do SDist,
confere bytes e avisos, e executa os testes instalados. O consumidor separado
usa apenas o wheel reconstruído em runtime somente leitura, sem checkout,
compilador ou backend de build. Artefatos e recibos ficam em `dist/`, limpo
antes de prepare/test; symlink nesse diretório é recusado. CI hospedado é uma
verificação separada.

Após instalar o wheel reconstruído em CPython3.13.18:

```sh
settlement-match-workbench demo --assert
settlement-match-workbench analyze --input fixtures/unique-input.json
```

O demo usa o SDK real e compara a Analysis inteira ao literal sintético
independente, inclusive sob `python -O`. Os bytes canônicos do SDK e seu LF
final são preservados. Falhas lógicas deixam stdout vazio; uma falha física de
escrita pode acontecer depois de um prefixo já enviado pelo sistema operacional.

## Limites e API

`settlement_match_workbench.financial.analyze_json(raw, limits)` recebe bytes
JSON fechados; `analyze(Scenario(...), limits)` recebe DTOs exatos. A API tipada
exige dinheiro `int` sem bool; a fronteira JSON exige strings canônicas. Não há
coerção de floats, chaves duplicadas, campos extras ou serializer público de
Analysis fornecida pelo caller.

Limites:1..8moedas,0..16lotes,0..16créditos,128candidatos, datas2000..2099 e
janelas inclusivas0..31dias. Todos os até256pares retêm motivos de rejeição.
Lotes líquidos zero permanecem como `NO_CREDIT_DUE`. Entrada e relatório têm
teto de524288bytes; o relatório inclui LF. O orçamento lógico é global:
50milhões por padrão, máximo100milhões. Exaustão resulta em UNKNOWN_BUDGET
sem Analysis, sem promessa geral de tempo ou desempenho.

Saídas CLI:0completo,2entrada/uso inválido,3I/O,4orçamento desconhecido,
5erro interno. Frames falhos vão para stderr. Arquivos regulares legíveis e
symlinks para regulares são aceitos; stdin precisa chegar a EOF. Não há rede,
credenciais, integração com instituição financeira ou escrita de arquivo pela
CLI. Veja [o contrato de I/O](CLI-IO.md) e [os avisos reais](../THIRD_PARTY.md).
