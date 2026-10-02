# Modelo de Tabulação — projeto de estudo (backend + frontend)

## Estrutura

```
tabulacao/
├── app.py                        <- Flask: recebe pedidos do navegador
├── requirements.txt
├── modelos/
│   └── Modelo_de_Estudo.xlsx     <- modelo REAL, já embutido no projeto
├── templates/index.html
├── static/{style.css,app.js}
├── src/tabulacao/
│   ├── data_reader.py
│   ├── column_mapper.py
│   ├── dedup.py                   <- regra de segurança (ver abaixo)
│   ├── pipeline.py
│   └── excel_writer.py            <- escreve no modelo real (ver abaixo)
└── tests/
    ├── test_dedup_seguranca.py
    └── test_excel_writer.py
```

## Como rodar

```bash
pip install -r requirements.txt
python app.py
```

Abra `http://localhost:5002`. **Você só precisa enviar a base de
vidas** — o modelo de tabulação já vem configurado dentro do projeto,
não precisa anexar.

## A regra de deduplicação

O sistema remove um registro **automaticamente, sem perguntar**, em
dois casos:

1. **Nome completo exatamente igual + mesma data de nascimento + mesmo
   CPF** batendo ao mesmo tempo (o critério principal); ou
2. Se a base enviada **não tem CPF disponível** (nenhuma coluna de CPF
   foi encontrada nela), **nome completo exatamente igual + mesma data
   de nascimento** já é suficiente — é o sinal mais forte possível de
   verificar quando não existe CPF pra comparar.

**Importante:** o caso 2 só vale quando a base inteira não tem CPF — se
a base TEM uma coluna de CPF, mas ela ficou vazia só para um par
específico de pessoas (preenchimento incompleto, não ausência da
coluna), isso NÃO confirma sozinho — vai para a revisão, porque faltar
o CPF ali pode ser só um esquecimento de preenchimento, não uma prova
de que são a mesma pessoa.

Qualquer outra coincidência (mesmo CPF sozinho sem nome/nascimento
baterem, mesma matrícula, nome parecido) vira **"Possível"**, e fica
numa tela de revisão pra você decidir — nunca é removida sozinha.

## Como a escrita no modelo real funciona

Preencher um modelo de Excel de verdade (não um arquivo em branco
criado do zero) trouxe três descobertas importantes, cada uma travada
com um teste automatizado específico em `tests/test_excel_writer.py`:

1. **`ws.cell(value=None)` não limpa célula no openpyxl.** Esse método
   trata `value=None` como "nenhum valor foi informado", não como
   "apagar" — então um campo vazio no registro novo (ex.: mensalidade
   não informada) ficava, por engano, com o valor de **exemplo** que já
   estava naquela célula do modelo. A correção usa
   `ws.cell(row, col).value = X` em vez do parâmetro `value=` do
   método `.cell()`.

2. **Idade e Faixa são fórmulas, calculadas a partir do Nascimento** —
   nunca escritas como valor fixo. A linha 2 do modelo tinha a Idade
   como número fixo (resquício de edição manual); o padrão de verdade
   está nas linhas "molde" mais pra baixo (ex.: linha 123, sem dado
   nenhum, só a fórmula pronta esperando preenchimento).

3. **Sexo depende de um arquivo externo que não viaja com o projeto.**
   A fórmula original faz um `VLOOKUP` numa tabela nome→sexo guardada
   em outro arquivo Excel. O arquivo guarda uma cópia em **cache**
   dessa tabela (quase 18.700 nomes), mas nem todo programa que abre o
   arquivo sabe usar esse cache ao recalcular (o LibreOffice, por
   exemplo, mostra `#NOME?`). Por segurança, em vez de copiar a
   fórmula, o sistema **lê essa mesma tabela em cache e calcula o Sexo
   diretamente em Python**, escrevendo o resultado como texto fixo —
   funciona em qualquer programa, sem depender de nenhum link externo.

## Capacidade: até 10.000 vidas

O modelo original só tinha espaço pronto pra ~250 pessoas. Ele foi
expandido (fórmulas de Idade/Faixa copiadas até a linha 10.001, fonte
da tabela dinâmica ajustada, e o resumo de texto — que antes ficava no
meio da área de dados — movido pra bem depois dela) pra comportar até
**10.000 vidas** de uma vez, mantendo a performance (testado: ~4
segundos pra escrever 10.000 registros no Excel).

## Performance com bases grandes (deduplicação)

Comparar nome parecido entre **todo mundo** com todo mundo fica
inviável em bases grandes — por isso o sistema agrupa por **3 letras
iniciais do nome** antes de comparar (em vez de 1 letra só, que em
bases de milhares de pessoas pode juntar milhares de gente com nome
comum no mesmo grupo). Se, mesmo assim, um grupo ficar maior que 400
pessoas, a comparação par a par dentro dele é pulada — nesse volume,
uma lista de "possíveis duplicidades" também deixaria de ser prática
de revisar numa tela.

## Titular/Dependente (TDA) e Sexo

**TDA (Tipo: Titular/Dependente):** se a base enviada já tem uma coluna
explícita de Tipo/T-D-A, o sistema usa ela direto. Se não tiver (o caso
mais comum — a maioria das bases de RH só tem "Parentesco"), o sistema
**deduz sozinho**: "Titular" vira T, qualquer outro parentesco
preenchido (Cônjuge, Filho, Filha, Enteado...) vira D.

**Sexo:** se a base já tem uma coluna de Sexo preenchida pra uma
pessoa (M, F, Masculino, Feminino...), o sistema usa esse valor real.
Só quando a base NÃO trouxe Sexo pra alguém específico é que o sistema
recorre à estimativa pelo primeiro nome (usando a tabela em cache do
próprio modelo — ver seção sobre o modelo real acima).

### Um bug real encontrado implementando isso

Ao testar com uma base real (célula de Sexo genuinamente vazia pra
algumas pessoas), a geração do arquivo quebrava com o erro `'float'
object has no attribute 'strip'`. A causa: quando uma célula de texto
do CSV está vazia, o pandas às vezes entrega isso como `NaN` (um tipo
`float` especial), não como `None` nem como texto vazio — e
`NaN or ""` em Python devolve o próprio `NaN` de volta (`NaN` é
considerado "verdadeiro" pelo Python, por mais estranho que pareça).
Corrigido tratando esse caso explicitamente em `pipeline.py`
(`_texto_ou_vazio`/`_numero_ou_none`) — afetava não só o Sexo, mas
também a Mensalidade.

## Rodando os testes

```bash
pip install pytest
pytest tests/ -v
```
