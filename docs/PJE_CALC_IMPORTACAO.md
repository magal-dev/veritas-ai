# PJe-Calc Cidadão 2.16.0: leiaute dos arquivos de importação

Análise feita só por leitura da instalação `pjecalc-windows64-2.16.0`, sem internet e sem rodar o sistema. Data: 22/10/2026.
O mapeamento do Veritas AI para estes arquivos está em [PJE_CALC_LAYOUT.md](PJE_CALC_LAYOUT.md).
Todos os exemplos deste documento são **fictícios**.

---

## 1. Onde está cada coisa e como foi verificado

**Estrutura**
- Webapp descompactado: `tomcat\webapps\pjecalc\` (Tomcat 7.0.67, JSF 1.2, RichFaces 3.3, Seam 2.2).
- Classes do sistema: os jars `WEB-INF\lib\pjecalc-base-2.16.0.jar`, `pjecalc-negocio-2.16.0.jar` e `pjecalc-integracao-2.16.0.jar`, e a pasta `WEB-INF\classes` (pacote `br.jus.trt8.pjecalc.web`).
- Mensagens: `WEB-INF\classes\messages.properties` (ISO-8859-1 com escapes `\uXXXX`).
- **Modelos de exemplo que vêm com o sistema** (são servidos pelo link "Para baixar um arquivo de exemplo preenchido, clique aqui"):
  - `templateCartaoDePonto\ExemploCartaoDePonto.csv` (quantidades)
  - `templateCartaoDePonto\ExemploJornadaCartaoDePonto.csv` (horários)
  - `templateHistoricoSalarial\ExemploHistoricoSalarial.csv`
  - `templateFerias\ExemploFerias.csv`
  - `templateFaltas\ExemploFaltas.csv`
- Inicialização: `iniciarPjeCalc.bat` sobe a JVM com `-Dfile.encoding=ISO-8859-1 -Duser.timezone=GMT-3`. Não define `user.language`, então o locale padrão da JVM é o do Windows (pt-BR nesta máquina).

**Método**
1. Jars extraídos para uma pasta temporária.
2. Bytecode desmontado com `javap -c -p -constants` (JDK 25).
3. Leitura das telas `.xhtml`, dos CSVs de exemplo (bytes, BOM e quebra de linha) e do `messages.properties`.
4. O PJe-Calc **não** foi iniciado, então não houve teste prático na interface.

**Mapa das importações**

| Importação | Tela (.xhtml) | Apresentador (web) | Parser (negócio) |
|---|---|---|---|
| Cartão de Ponto: quantidades | `pages/cartaodeponto/cartaodeponto.xhtml` | `ApresentadorCartaoDePonto.importarCSV()` | `ServicoDeParsingDeCartaoDePonto.importarCartaoDePonto()` → `CartaoDePonto.gerarCartaoDePontoEOcorrenciasDoCartaoDePonto()` |
| Cartão de Ponto: jornada (horários) | `pages/cartaodeponto/apuracao-cartaodeponto.xhtml`, aba "Importar Jornada" | `ApresentadorApuracaoCartaoDePonto.importarCSV()` | `ServicoDeParsingDeCartaoDePonto.importarJornadaCartaoDePonto()` → `ApuracaoCartaoDePonto.gerarCartaoDePontoEOcorrenciasDoCartaoDePonto(List)` |
| Histórico Salarial | `pages/calculo/historico-salarial.xhtml` | `ApresentadorHistoricoSalarial.importarCSV()` | `ServicoDeParsingDeHistoricoSalarial` (herda de `AbstractServicoDeParsing`) |
| Férias | `pages/calculo/ferias.xhtml` | `ApresentadorFerias.importarCSV()` | `ServicoDeParsingDeFerias` (herda de `AbstractServicoDeParsing`) |
| Faltas | `pages/calculo/falta.xhtml` | `ApresentadorFalta.importarCSV()` | `ServicoDeParsingDeFaltas` (herda de `AbstractServicoDeParsing`) |
| Outras: cálculo `.PJC` | `pages/importacao/importacao.xhtml` | `ApresentadorImportacao.importarZip()` | `negocio.comum.Importador` |
| Outras: tabelas auxiliares | `pages/replicacao/replicacao.xhtml`, aba "Importar Via Arquivo" | `ApresentadorSincronizacao.importar()` | `ServicoDeSincronizacaoDeTabelas.importarArquivoDeSincronizacao()` |

Nenhuma importação usa OpenCSV, Commons CSV ou POI. Todas são parsers manuais com `String.split`/`StringUtils.splitPreserveAllTokens`, `SimpleDateFormat` e `DecimalFormat`. Não existe importação de planilha `.xls`/`.xlsx`.

---

## 2. Regras comuns a Histórico Salarial, Férias e Faltas

As três usam a mesma classe base, `AbstractServicoDeParsing`:

- **Codificação:** lidas como **UTF-8**, fixo no código. Se o arquivo tiver BOM, ele não atrapalha, porque cai na linha 1, que é ignorada. Um arquivo salvo em ANSI/ISO-8859-1 com acentos (por exemplo, na justificativa da falta) fica com caracteres corrompidos.
- **Cabeçalho:** a **linha 1 é sempre descartada** e o conteúdo dela não é conferido. Mesmo assim, ela precisa existir: sem ela, o primeiro registro some. Use os nomes do modelo por clareza.
- **Associação de colunas:** pela **posição**, não pelo nome. Não há tela de mapeamento.
- **Aspas:** todas as aspas duplas `"` da linha são **removidas antes** da separação. Elas são opcionais e **não protegem** um `;` dentro do texto. Apóstrofos são mantidos.
- **Separador de campos:** `;`.
- **Quebra de linha:** CRLF ou LF (lidas com `readLine`).
- **Linhas em branco:** uma linha vazia no meio ou no fim gera o erro *"Foram encontrados valores inválidos na linha N do arquivo importado."* (MSG0191). Não deixe linhas vazias, nem uma linha vazia extra no final.
- **Arquivo vazio ou só com cabeçalho:** MSG0191 com "linha 0".
- **Numeração das linhas nas mensagens:** conta a partir de 1, com o cabeçalho sendo a linha 1. Bate com o número da linha no editor.
- **Booleanos:** `S` ou `N`, sem diferenciar maiúsculas de minúsculas. Vazio vira "não informado" (o efeito de cada campo está nas seções). Qualquer outro valor dá *"Valor inválido encontrado. Valores permitidos [S,N]. Erro na linha N do arquivo."* (MSG0194).
- **Datas:** `SimpleDateFormat` no modo **leniente** (padrão do Java). Por isso, `31/02/2020` é aceito e vira 02/03/2020. Erro de formato: *"Valor inválido para data. A data deve estar no formato [dd/MM/yyyy]. Erro na linha N do arquivo."* (MSG0193; para competência, o formato mostrado é `[MM/yyyy]`).
- **Números:** `DecimalFormat("#,##0.00")` no **locale padrão da JVM** (pt-BR): decimal `,` e milhar `.`. O parse é parcial: lê até o primeiro caractere inválido. Erro: *"Valor inválido para numérico. O número deve estar no formato [9,99]. Erro na linha N do arquivo."* (MSG0195).
- **Extensão:** a tela não restringe o tipo do arquivo, e essas três importações **não conferem a extensão**. Na prática, use `.csv`.
- **Tamanho:** o limite do upload é `maxRequestSize = 20480000` bytes (cerca de 20 MB, no `web.xml`). Não há limite de linhas no código.
- **Arquivo não selecionado:** *"Campo obrigatório: Selecionar Arquivo CSV"* (MSG0003).
- **Sucesso:** MSG0001, a mensagem padrão de operação realizada.

---

## 3. Cartão de Ponto: importação de QUANTIDADES

Tela: **Cartão de Ponto → "Importar - Gerar os Valores de Cartão de Ponto a Partir de Arquivo Externo"**. Cada coluna de dados vira um "Cartão de Ponto" com nome próprio, e as verbas podem usá-lo como quantidade importada.

### Formato do arquivo
- **Extensão:** o nome do arquivo **precisa terminar em `.csv`** (sem diferenciar maiúsculas). Se não terminar, aparece *"Arquivo de Cartão de Ponto Inválido."* (MSG0120).
- **Codificação:** charset padrão da JVM, que é **ISO-8859-1** por causa do `-Dfile.encoding` do `.bat`. Use ANSI/Latin-1 se houver acentos nos nomes das colunas. Em UTF-8, os acentos dos nomes ficam corrompidos.
- **Separador:** `;`. Uma linha **sem nenhum `;`** é tratada como separada por vírgula. Nesse modo, números decimais com vírgula precisam estar entre aspas (`"10,5"`) para serem preservados. Essa decisão é tomada **linha a linha**.
- **Cabeçalho:** obrigatório. Define o **número de colunas** (máximo **16**; acima disso, *"O arquivo de Cartão de Ponto deve possuir no máximo 16 colunas."*, MSG0121).
  - A **coluna 1** é a data/competência. O nome dela é ignorado (o modelo usa `DATAS`).
  - **Colunas 2 a 16:** o texto do cabeçalho vira o **nome do cartão** que aparece no sistema (as aspas são removidas). Os nomes são livres. O modelo usa `QT. H. EXT`, `QT. H. TRA`, `QT. H. NOT` e `QT. RSR`.
- Colunas além das que o cabeçalho declara são ignoradas em cada linha.

### Colunas

| # | Nome (exemplo) | Formato | Obrigatório | Observações |
|---|---|---|---|---|
| 1 | `DATAS` | competência `MM/yyyy`. Também aceita `dd/MM/yy`, `MMMM/yy`, `MMMM/yyyy` (mês por extenso, em pt-BR: `janeiro/2013`) e `MM/yy` | Sim | Formatos testados nesta ordem: `dd/MM/yy`, `MM/yyyy`, `MMMM/yy`, `MMMM/yyyy`, `MM/yy`. Se nenhum servir: *"Data em formato inválido."* (MSG0122) |
| 2..16 | nome livre (ex.: `QT. H. EXT`) | decimal com vírgula, padrão `#,##0.0000` em pt-BR (ex.: `10,5000`, `1.234,25`) | Sim, todas as células | Pode ter aspas (simples ou duplas). Não pode ser negativo: *"A quantidade no Cartão de Ponto não pode ser menor que zero."* (MSG0124). Para zero, use `0`. Célula vazia gera MSG0120. Célula faltando (linha com menos colunas que o cabeçalho) gera um erro não tratado |

### Comportamento
- Cada linha vira uma ocorrência (data + quantidade) para **cada** coluna de dados.
- **Atenção:** durante a importação, o código chama a remoção de **todas as apurações de cartão de ponto** (jornadas) existentes no cálculo, antes de salvar os cartões importados.
- Não há códigos para folga, feriado ou falta. São só quantidades numéricas por competência.
- A lista `TipoDeQuantidadeImportadaDoCartaoDePontoEnum` (HED, HEN, HEDN, HN, R, F, RF, ITRA, ITER) pertence à configuração da **verba**. Ela não faz parte do leiaute do arquivo.

### Exemplo fictício (separador `;`, ISO-8859-1)
```csv
DATAS;QT. H. EXT;QT. H. NOT;QT. RSR
01/2021;12,5000;40,0000;4,0000
02/2021;8,2500;36,0000;4,0000
03/2021;0;44,0000;5,0000
04/2021;15,7500;40,0000;4,0000
```
O modelo oficial usa vírgula como separador e números entre aspas (`01/2013,"10,5000",...`). Esse formato também funciona, pela regra da linha sem `;`.

---

## 4. Cartão de Ponto: importação dos HORÁRIOS da jornada

Tela: **Cartão de Ponto → (apuração) → aba "Importar Jornada"**, botão Confirmar.

### Pré-requisito importante
A importação **só atualiza dias que já existem** nas apurações de cartão de ponto do cálculo. Para cada apuração, o sistema procura no arquivo a linha com a mesma data. Datas fora do período das apurações são **ignoradas sem aviso**, e, se não houver apuração nenhuma, a importação "dá certo" sem fazer nada. Portanto, **cadastre antes a apuração** (botão Novo, com o período) e depois importe.

### Formato do arquivo
- **Extensão:** precisa terminar em `.csv`; senão, MSG0120.
- **Codificação:** ISO-8859-1, o padrão da JVM. Como o cabeçalho é ignorado e o resto é só números, UTF-8 ou BOM não atrapalham na prática. O próprio modelo oficial está em UTF-8 sem BOM.
- **Separador:** `;`. Vale a mesma regra de vírgula para linhas sem `;` descrita na seção 3.
- **Cabeçalho:** obrigatório, até **13 colunas**. Acima disso aparece MSG0121, cujo texto fala em "16 colunas" mesmo neste caso. Os nomes não são conferidos, mas **a quantidade de colunas do cabeçalho limita o que é lido**: se o cabeçalho tiver 5 colunas, só os 2 primeiros turnos são importados.
- **Colunas:** posição fixa. Índices no código: entrada 1 = 1, saída 1 = 2, …, saída 6 = 12.

| # | Nome (modelo) | Formato | Obrigatório | Observações |
|---|---|---|---|---|
| 1 | `Data` | `dd/MM/yy` (ano com 4 dígitos também funciona: `29/10/2018`) | Sim | Leniente. Data inválida gera *"Data em formato inválido."* (MSG0122) |
| 2 | `Entrada1` | `HH:mm` | Não | **exatamente 5 caracteres**. Horas de 00 a 23, minutos de 00 a 59 |
| 3 | `Saída1` | `HH:mm` | Não | idem |
| 4–5 | `Entrada2`, `Saída2` | `HH:mm` | Não | |
| 6–7 | `Entrada3`, `Saída3` | `HH:mm` | Não | |
| 8–9 | `Entrada4`, `Saída4` | `HH:mm` | Não | |
| 10–11 | `Entrada5`, `Saída5` | `HH:mm` | Não | |
| 12–13 | `Entrada6`, `Saída6` | `HH:mm` | Não | |

### Regras de validação
- Espaços em volta dos horários são removidos.
- Um valor que **não tem 5 caracteres** (por exemplo, `8:00` ou `08:00:00`) é **descartado sem aviso** e conta como vazio. Use sempre dois dígitos: `08:00`.
- Cada turno precisa ter **entrada e saída**. Turno com só uma das duas, ou com hora/minuto fora da faixa (por exemplo, `24:00`), gera *"Sempre deve haver uma hora de entrada e saída válida para um turno preenchido. Verifique a data: dd/MM/aaaa."* (MSG0164).
- Um texto de 5 caracteres que não seja numérico (por exemplo, `08h00`) gera erro não tratado.
- Uma saída menor que a entrada (por exemplo, `13:50` até `00:00`) é aceita: o sistema entende que o turno vira o dia. O modelo oficial tem esse caso.
- **Dia sem marcação (folga, DSR, feriado, falta):** deixe todas as colunas de horário vazias (`04/11/2018;;;;;;;;;;;;` ou só `04/11/2018`). Não existem códigos para folga, feriado ou falta neste arquivo. Feriados e faltas vêm de outros cadastros do cálculo.
- Os 12 campos do dia são **sobrescritos** (vazio apaga o que havia) e o dia fica marcado como "alterado manualmente". Dias que não aparecem no arquivo continuam como estavam.

### Exemplo fictício
```csv
Data;Entrada1;Saída1;Entrada2;Saída2;Entrada3;Saída3;Entrada4;Saída4;Entrada5;Saída5;Entrada6;Saída6
03/05/2021;08:00;12:00;13:00;17:30;;;;;;;;
04/05/2021;07:55;12:05;13:10;18:45;;;;;;;;
05/05/2021;08:00;12:00;13:00;17:00;19:00;22:00;;;;;;
08/05/2021;;;;;;;;;;;;
09/05/2021;22:00;02:00;03:00;06:00;;;;;;;;
```

---

## 5. Histórico Salarial (CSV)

Tela: **Histórico Salarial → (abrir ou criar um histórico, por exemplo "Salário") → "Importar ocorrências… a partir de Arquivo Externo"**. A importação acontece **dentro do registro de histórico aberto**. Aviso da tela: *"Após realizar a importação via arquivo externo, os dados anteriormente cadastrados serão excluídos."* Todas as ocorrências daquele histórico são substituídas.

Regras gerais: seção 2 (UTF-8, `;`, linha 1 ignorada, aspas removidas).
Separação com `splitPreserveAllTokens`, que mantém campos vazios. A linha precisa ter **pelo menos 6 campos** (5 `;`); senão, MSG0191.

| # | Nome (modelo) | Formato | Obrigatório | Observações |
|---|---|---|---|---|
| 1 | `MES_ANO` | competência `MM/yyyy` | **Sim** | Vazio gera MSG0191. Formato errado gera MSG0193 `[MM/yyyy]` |
| 2 | `VALOR` | `#,##0.00` em pt-BR: `1.234,56`, `1234,56` ou `500` | Não | Vazio vira **0**. Cuidado: `1234.56` (ponto decimal) é lido como 123456, porque o ponto é separador de milhar em pt-BR. Texto inválido (ex.: `R$ 10`) gera MSG0195 |
| 3 | `FGTS` | `S`/`N` | Não | Incidência de FGTS. Vazio vira N |
| 4 | `FGTS_REC.` | `S`/`N` | Não | FGTS já recolhido. Vazio vira N |
| 5 | `CONTRIBUICAO_SOCIAL` | `S`/`N` | Não | Incidência de contribuição social (INSS). Vazio vira N |
| 6 | `CONTRIBUICAO_SOCIAL_REC.` | `S`/`N` | Não | Contribuição social já recolhida. Vazio vira N |

Depois da leitura, o sistema (`organizarHistoricoComBaseNaImportacao`):
- define a competência inicial e a final como a menor e a maior do arquivo;
- **preenche os meses que faltam** no intervalo (`preencherGapDeOcorrencias`);
- ajusta as marcações gerais de FGTS e contribuição social do histórico a partir das ocorrências.

### Exemplo fictício (UTF-8)
```csv
"MES_ANO";"VALOR";"FGTS";"FGTS_REC.";"CONTRIBUICAO_SOCIAL";"CONTRIBUICAO_SOCIAL_REC."
"01/2022";"1.850,00";"S";"N";"S";"N"
"02/2022";"1.850,00";"S";"N";"S";"N"
"03/2022";"1.920,50";"S";"S";"S";"S"
"04/2022";"1.920,50";"S";"N";"S";"N"
```
As aspas são opcionais: `01/2022;1850,00;S;N;S;N` é equivalente.

---

## 6. Férias (CSV)

Tela: **Férias → "Importar … a partir de Arquivo Externo"**. Aviso: *"Após realizar a importação via arquivo externo, os dados anteriormente cadastrados serão excluídos."*

**Ponto crucial:** a importação **não cria períodos aquisitivos**. Cada linha procura, entre as férias que o sistema **já gerou** para o cálculo (a partir de admissão e demissão), aquela cuja relativa é igual à coluna `RELATIVAS` (comparação sem diferenciar maiúsculas e sem espaços nas pontas). Se não encontrar: *"As férias definidas no arquivo não podem ser anterior a Data de Admissão e nem posterior a Data de Demissão/Data Final definida para o cálculo. Erro na linha N do arquivo."* (MSG0192).

Regras gerais: seção 2. A linha precisa ter **pelo menos 15 campos** (14 `;`), mesmo que os últimos estejam vazios; senão, MSG0191.

| # | Nome (modelo) | Formato | Obrigatório | Observações |
|---|---|---|---|---|
| 1 | `RELATIVAS` | `AAAA/AAAA` (ex.: `2020/2021`) | **Sim** | Precisa ser igual ao período aquisitivo exibido pelo sistema |
| 2 | `PRAZO` | inteiro (dias: 30, 20, 0…) | **Sim** | Vazio ou não numérico gera MSG0191 |
| 3 | `SITUACAO` | `G`, `GP`, `NG`, `I`, `P` | **Sim** | G = Gozadas, GP = Gozadas Parcialmente, NG = Não Gozadas, I = Indenizadas, P = Perdidas (sem diferenciar maiúsculas). Código inválido provavelmente gera MSG0191 (ver incertezas) |
| 4 | `DOBRA` | `S`/`N` | Não | Dobra geral. Vazio vira N. É forçada a N quando a situação é G ou P |
| 5 | `ABONO` | `S`/`N` | Não | Abono pecuniário. Vazio vira N. É forçado a N quando a situação é I ou P |
| 6 | `QTD_DIAS_ABONO` | inteiro | Não | Vazio vira 0 |
| 7 | `G1INI` | `dd/MM/yyyy` | Não | Início do 1º período de gozo |
| 8 | `G1FIM` | `dd/MM/yyyy` | Não | Fim do 1º período de gozo |
| 9 | `G1DOBRA` | `S`/`N` | Não | Dobra do 1º período. Vazio vira N |
| 10–12 | `G2INI`, `G2FIM`, `G2DOBRA` | idem | Não | 2º período de gozo |
| 13–15 | `G3INI`, `G3FIM`, `G3DOBRA` | idem | Não | 3º período de gozo |

### Exemplo fictício (UTF-8; supõe admissão em 01/03/2020)
```csv
RELATIVAS;PRAZO;SITUACAO;DOBRA;ABONO;QTD_DIAS_ABONO;G1INI;G1FIM;G1DOBRA;G2INI;G2FIM;G2DOBRA;G3INI;G3FIM;G3DOBRA
2020/2021;30;G;N;S;10;10/05/2021;29/05/2021;N;;;;;;
2021/2022;30;GP;N;N;0;03/10/2022;12/10/2022;N;;;;;;
2022/2023;30;G;N;N;0;09/01/2023;18/01/2023;N;03/04/2023;12/04/2023;N;02/10/2023;11/10/2023;N
2023/2024;30;I;N;N;0;;;;;;;;;
```

---

## 7. Faltas (CSV)

Tela: **Faltas → "Importar ocorrências de Faltas a partir de Arquivo Externo"**. Aviso: *"Após realizar a importação via arquivo externo, todos as ocorrências de faltas já cadastradas serão excluídas."* O código apaga todas as faltas antes de gravar as importadas.

Regras gerais: seção 2. **Diferença:** aqui a separação usa `String.split(";")`, que **descarta campos vazios no fim da linha**. Por isso, as 4 primeiras colunas precisam estar presentes, e a 4ª não pode ser vazia quando for a última. Na prática, preencha sempre `INICIO`, `FIM`, `JUSTIFICADA` e `REINICIAR_PER_AQ`.

| # | Nome (modelo) | Formato | Obrigatório | Observações |
|---|---|---|---|---|
| 1 | `INICIO` | `dd/MM/yyyy` | **Sim** | Início do período de falta |
| 2 | `FIM` | `dd/MM/yyyy` | **Sim** | Fim do período (igual ao início para um único dia) |
| 3 | `JUSTIFICADA` | `S`/`N` | **Sim** | `S` = falta justificada, `N` = não justificada |
| 4 | `REINICIAR_PER_AQ` | `S`/`N` | **Sim** | `S` = a falta reinicia o período aquisitivo de férias. Nesse caso, o sistema regera as férias e mostra a lista das férias alteradas |
| 5 | `JUSTIFICATIVA` | texto livre | Não | Truncado em **200 caracteres**. Não pode conter `;` nem `"` (aspas são removidas). Acentos exigem UTF-8 |

Depois da leitura, cada falta é salva pela mesma rotina do cadastro manual (`Falta.salvar`). As validações de negócio do cadastro manual, como período dentro do contrato e sobreposição, devem valer também na importação (ver incertezas).

### Exemplo fictício (UTF-8)
```csv
"INICIO";"FIM";"JUSTIFICADA";"REINICIAR_PER_AQ";"JUSTIFICATIVA"
"15/03/2021";"17/03/2021";"S";"N";"Atestado médico fictício"
"02/08/2021";"02/08/2021";"N";"N";
"10/01/2022";"14/02/2022";"N";"S";"Licença não remunerada (exemplo)"
"20/06/2022";"20/06/2022";"S";"N";"Doação de sangue"
```

---

## 8. Outras importações de arquivo encontradas

1. **Importação de cálculo (`.PJC`).** Menu Importação → "Arquivo do PJe-Calc". É o arquivo exportado pelo próprio PJe-Calc: um ZIP (o `TipoDeArquivoEnum` associa PJC a `application/zip`). Mensagens: *"Arquivo inválido."* (MSG0064) e o aviso MSG0116, segundo o qual feriados, pisos salariais e vales-transporte locais não são importados quando o cálculo vem de outra regional. O conteúdo interno é proprietário e não foi detalhado.
2. **Atualização de tabelas auxiliares por arquivo.** Tela Replicação/Sincronização → "Importar Via Arquivo". Recebe um arquivo compactado (o código chama `Utils.unzip`) gerado pelo próprio sistema ou pelo tribunal. Erro: MSG0064.
3. **Anexos/documentos** (`pages/comum/documentoModalPanel.xhtml` e `fileuploadModelPanel.xhtml`). São uploads genéricos de anexos com `acceptedTypes` configurável. Não fazem importação de dados.

---

## 9. Pontos incertos e nível de confiança

| Item | Confiança | Comentário |
|---|---|---|
| Colunas, ordem e formatos de data/competência/booleano das 5 importações CSV | **Alta** | Lidos direto do bytecode e conferidos com os modelos oficiais |
| UTF-8 em Histórico, Férias e Faltas | **Alta** | `StandardCharsets.UTF_8` fixo no código |
| ISO-8859-1 no Cartão de Ponto (quantidades e jornada) | **Alta** se o sistema for iniciado pelo `iniciarPjeCalc.bat` | Usa o charset padrão da JVM. Outro lançador mudaria isso |
| Separador decimal do Histórico Salarial (`,`) | **Média-alta** | Depende do locale padrão da JVM, que segue o Windows (pt-BR aqui). Em um Windows com locale inglês, `1.850,00` seria lido de forma errada |
| Comportamento de célula vazia ou faltando na importação de quantidades | **Média** | Vazio gera MSG0120. Célula faltando gera um erro genérico não tratado, cuja mensagem exata não foi verificada na interface |
| Código de `SITUACAO` inválido em Férias | **Média** | A consulta ao código não foi confirmada (a sessão caiu durante essa checagem). O mais provável é que retorne nulo e cause MSG0191 |
| Férias de períodos que não estão no arquivo | **Média** | O código só altera os períodos encontrados. A tela diz que "os dados anteriormente cadastrados serão excluídos", mas não foi comprovado se os períodos ausentes são apagados ou mantidos |
| Persistência das férias importadas sem clicar em Salvar | **Média-baixa** | O `importarCSV` de Férias não chama salvar explicitamente. A gravação pode depender do flush do Seam ou de uma ação posterior |
| Validações de negócio pós-importação de Faltas (período no contrato, sobreposição, falta justificada vazia) | **Média** | Feitas por `Falta.salvar` e pelas regras Drools (`pjecalc.validacao.pkg`), que não foram analisadas em detalhe |
| Preenchimento dos meses faltantes no Histórico (valor usado: zero ou repetição do anterior) | **Média-baixa** | Existe `preencherGapDeOcorrencias`, mas o valor de preenchimento não foi verificado |
| A importação de quantidades remove as apurações de jornada existentes | **Média-alta** | Visto no bytecode (`ApuracaoCartaoDePonto.remover` dentro do laço). Não foi testado na interface |
| Limites | **Alta** | 16 colunas (quantidades), 13 (jornada), 200 caracteres (justificativa), cerca de 20 MB por upload. Não há limite de linhas ou de período no parser |
| Passos na interface | **Média** | Deduzidos dos `.xhtml`. O PJe-Calc não foi executado |
