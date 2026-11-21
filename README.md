# Fenotipagem Digital

Sistema web para fenotipagem de ensaios agrícolas com imagens de drone. Você cadastra o ensaio e os tratamentos, envia o ortomosaico RGB de cada voo, marca o croqui sobre a imagem, e o servidor calcula índices de vegetação por parcela e em grade. Os resultados aparecem num mapa interativo e numa análise estatística por tratamento.

## Fluxo

1. **Ensaio**: nome, cliente, local, cultura, variedade, observações e tratamentos (nº, sigla, produto/dose e qual é o controle).
2. **Voos**: um ortomosaico por data (GeoTIFF, JPG ou PNG). O servidor lê o arquivo, gera a pré-visualização do mapa e calcula o limiar planta × solo (Otsu).
3. **Croqui**: marque os 4 cantos da área das parcelas, defina linhas, colunas, bordadura e o tamanho da grade. Identifique cada parcela com o nº do tratamento e a letra do bloco (ex.: `4A`), digitando, colando do Excel ou sorteando um DBC. Os cantos ficam em latitude/longitude, então o mesmo croqui serve para todos os voos georreferenciados.
4. **Mapa**: o servidor calcula os índices em resolução total, lendo só a janela de cada parcela (arquivos de vários GB não precisam caber na memória). No mapa dá para escolher o voo, o índice e as camadas: tratamento, parcela, índice por parcela, índice em grade e máscara de vegetação.
5. **Resultados**: médias por tratamento, ANOVA (DBC quando todos os tratamentos aparecem em todos os blocos, senão DIC), teste DMS (t) a 5% ou 10% com letras, ganho sobre o controle, evolução entre voos e exportação em Excel, CSV e GeoJSON.

## Índices calculados

| Índice | Fórmula | Referência |
|---|---|---|
| CC (cobertura vegetal, %) | pixels com ExG acima do limiar ÷ pixels da parcela | — |
| ExG | 2g − r − b (r, g, b normalizados pela soma) | Woebbecke et al. (1995) |
| ExGR | ExG − (1,4r − g) | Meyer & Neto (2008) |
| VARI | (G − R) / (G + R − B) | Gitelson et al. (2002) |
| GLI | (2G − R − B) / (2G + R + B) | Louhaichi et al. (2001) |
| NGRDI | (G − R) / (G + R) | Tucker (1979) |
| MGRVI | (G² − R²) / (G² + R²) | Bendig et al. (2015) |
| RGBVI | (G² − B·R) / (G² + B·R) | Bendig et al. (2015) |
| ExG da planta | ExG médio só dos pixels de planta | — |

O limiar de planta × solo é o de Otsu sobre o ExG de cada imagem, limitado entre 0,02 e 0,20, ou um valor fixo escolhido no ensaio. Pixels muito escuros (sombra) não contam como planta.

## Estrutura

```
backend/   API em Python (FastAPI). Leitura do ortomosaico com rasterio, cálculo com numpy, estatística com scipy
  app/main.py       rotas da API e site
  app/raster.py     pré-visualização e índices
  app/geometry.py   croqui → parcelas e grade
  app/stats.py      ANOVA, DMS e letras
  app/db.py         banco (SQLite local ou Postgres/Supabase)
  tests/            teste do fluxo completo com um GeoTIFF sintético
frontend/  site (HTML, CSS e JavaScript, sem build)
```

## Rodar no seu computador sem Docker (macOS ou Linux)

Precisa de Python 3.10 ou mais novo.

```bash
./iniciar.sh   # na primeira vez cria o .env: preencha ADMIN_EMAIL, ADMIN_PASSWORD e DATABASE_URL
./iniciar.sh   # instala o que falta e sobe o servidor em http://localhost:8000
```

As imagens ficam na pasta `dados/`.

## Rodar no seu computador (Docker)

```bash
cp .env.example .env      # preencha SECRET_KEY, ADMIN_EMAIL e ADMIN_PASSWORD
docker compose up -d --build
```

Abra http://localhost:8000 e entre com o e-mail e a senha do administrador. Na tela **Equipe** o administrador cadastra as outras pessoas.

As imagens ficam no volume `dados` e o banco no volume `banco`.

## Usar o banco do Supabase

No Supabase, abra *Project Settings → Database → Connection string → URI*, troque `postgresql://` por `postgresql+psycopg://` e coloque em `DATABASE_URL` no `.env`. As tabelas são criadas sozinhas na primeira vez que o servidor sobe. Para usar o mesmo projeto do INOVAAGRO sem misturar as tabelas, defina `DB_SCHEMA=fenotipagem`: tudo fica num schema separado.

O Supabase guarda o banco, mas não roda o servidor Python. O servidor precisa de um lugar com Docker (veja abaixo).

## Publicar num servidor

Qualquer serviço que rode Docker serve (Render, Railway, Fly.io, uma VPS). O servidor precisa de:

- um **disco persistente** montado em `/dados` (os ortomosaicos ficam lá);
- as variáveis `SECRET_KEY`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` e `DATABASE_URL`;
- limite de upload compatível com o tamanho dos ortomosaicos (alguns serviços cortam envios muito grandes).

## Desenvolvimento

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest
ADMIN_EMAIL=admin@teste.com ADMIN_PASSWORD=senha123 uvicorn app.main:app --reload
```

## Próximos passos

- Importar o croqui de KML ou shapefile.
- Relatório em PDF no formato dos relatórios de ensaio.
- Guardar os ortomosaicos no Supabase Storage ou S3 e enviar arquivos grandes em partes.
- Altura de plantas a partir do modelo digital de superfície (DSM) e índices multiespectrais (NDVI, NDRE).
- Teste de Scott-Knott e Tukey.
