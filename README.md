# tradingbot

Laboratorio de trading algorítmico sobre Bitso, construido alrededor de una
sola idea: **con capital chico, los costos deciden el resultado.** Todo el
diseño existe para que eso sea imposible de ignorar.

## Por qué este repo existe

Con 33 USDC de capital y un costo de ida y vuelta de ~1.6% por operación, diez
operaciones mensuales cuestan el 16% del capital. Ninguna estrategia razonable
supera eso de forma sostenida.

```
$ python -m tradingbot costs
  taker              65.0 bps
  maker              50.0 bps
  medio spread       10.0 bps
  slippage            5.0 bps
  ida y vuelta      160.0 bps = 1.60 % por operacion

Con 33.27 de capital: 0.532 por operacion completa.
10 operaciones al mes = 5.32 (16.0% del capital).
```

Entonces el objetivo del proyecto **no es hacer crecer 33 dólares**. Es
construir y validar el sistema, medido honestamente, para que tenga sentido el
día que el capital justifique operarlo. El capital crece por aportes; el
sistema crece por evidencia.

## Estado

Fase 1 de 3. No opera con dinero real y no puede hacerlo: el cliente de
exchange no implementa colocación de órdenes.

| Fase | Qué | Estado |
|---|---|---|
| 0 | Infraestructura, backtest con costos, journal | listo |
| 1 | Recolección sostenida + paper trading, ≥100 trades | **código listo, juntando datos** |
| 2 | Capital real mínimo, una estrategia, límites duros | bloqueada por Fase 1 |
| 3 | Escalar por aportes mensuales | — |

El criterio para pasar de Fase 1 a Fase 2 es explícito y lo contesta el
código, no el entusiasmo: **≥100 operaciones completas simuladas con
expectancy positiva después de costos.** Si no se cumple, no se pasa.

```bash
python -m tradingbot gate --tf 1h    # veredicto de la fase
```

Sale con código 0 solo si el criterio se cumple, así que sirve en un script.
El mismo veredicto está en el dashboard y en `GET /api/phase`.

Lo que la Fase 1 bloquea no es código, es **tiempo**: hacen falta semanas de
mercado real. El `gate` estima cuánto falta usando el ritmo observado de velas,
no el nominal del timeframe — en un libro poco líquido no hay una vela por
intervalo, solo donde hubo trades.

## Arranque rápido

Sin dependencias externas: el core corre solo con la biblioteca estándar.

```bash
# Ver el modelo de costos aplicado a tu capital
python -m tradingbot costs

# Cargar datos sintéticos y correr el pipeline completo, sin red
python -m tradingbot demo --shape sine --n 400
python -m tradingbot --book DEMO_sine backtest --tf 1h

# Tests
pip install -e '.[dev]' && pytest
```

El backtest sobre el mercado lateral sintético muestra el punto del proyecto:
el cruce de medias pierde 58% mientras el precio termina donde empezó, y
comprar y no tocar nada pierde solo la comisión de entrada.

## Con datos reales

Requiere acceso de red a `api.bitso.com`.

```bash
python -m tradingbot books                      # pares y montos mínimos
python -m tradingbot spread --book usdc_ars      # spread real, ahora
python -m tradingbot calibrate --book usdc_ars   # medir en vez de suponer
python -m tradingbot collect --book usdc_ars     # correr sostenido, ver abajo
python -m tradingbot --book usdc_ars backtest --tf 1h
python -m tradingbot --book usdc_ars paper --tf 1h     # procesa velas cerradas
python -m tradingbot --book usdc_ars gate --tf 1h      # veredicto de la fase
```

**Correr `calibrate` varias veces al día.** Guarda cada medición en vez de
pisarla y el modelo usa la *mediana* del medio spread: el spread se abre y se
cierra durante el día, y una sola lectura puede caer justo en el mejor momento
y subestimar el costo real. Mientras no haya mediciones, el dashboard marca los
costos como `ESTIMADO`, porque tratar un default como si fuera dato es
exactamente como se construye un backtest que miente.

**Paper trading sostenido:** el collector corre el motor de papel después de
cada ciclo, dentro del mismo proceso.

```bash
python -m tradingbot.daemon --book usdc_ars --interval 60 --paper --tf 1h
```

Un solo proceso escribiendo en SQLite, y las velas se procesan recién cuando ya
se guardaron. El motor **nunca opera la vela en formación** (sigue recibiendo
trades, así que la señal cambiaría a medida que llegan), el estado sobrevive a
reinicios, y el `run_id` es estable: un redeploy continúa la misma corrida en
vez de partir la evidencia en pedazos.

**Verificar el libro antes de dejarlo corriendo.** Los nombres de libro varían
por país y cambian con el tiempo:

```bash
python -m tradingbot books | grep -i usdc
```

El daemon verifica el libro al arrancar y aborta con un error explícito si no
existe, en vez de reintentar en silencio para siempre. Un fallo de red no
aborta: eso lo maneja el backoff.

**Sobre la historia de precios:** Bitso v3 no expone un endpoint público
documentado de velas OHLCV. `collect` baja los trades públicos y arma las velas
localmente. Consecuencia práctica: no hay historia profunda disponible de
entrada, y el collector tiene que correr sostenidamente (cron, cada pocos
minutos) antes de que un backtest tenga significancia estadística. No hay atajo.

## Dashboard y landing

Hay una interfaz web de solo lectura sobre el journal: landing con la tesis del
proyecto y dashboard con cobertura de datos, curva de equity, operaciones y
rechazos.

```bash
# Local, sin Docker
pip install -r services/api/requirements.txt
PYTHONPATH=src:services/api TRADING_DB_PATH=data/trading.db DASHBOARD_TOKEN=dev \
  python -m uvicorn app.main:app --port 8000
```

El panel **observa, no opera**: monta la base con `:ro`, abre SQLite en modo
solo lectura y no tiene acceso a las credenciales de Bitso. Solo el collector
escribe, y solo él recibe las credenciales.

## Despliegue

El `docker-compose.yml` y el `.env.example` están en la raíz, así que el VPS
clona este repo y se actualiza con `git pull`:

```bash
git clone https://github.com/pel-matiasvaldivia/trading.git /opt/tradingbot
cd /opt/tradingbot
cp .env.example .env    # completar DASHBOARD_TOKEN
docker compose pull && docker compose up -d
```

Las imágenes las construye GitHub Actions y se publican en GHCR; en el VPS no
se compila nada. Pasos completos, incluida la configuración del Proxy Host en
Nginx Proxy Manager y los puertos publicados, en **[deploy/README.md](deploy/README.md)**.

## Arquitectura

```
collector  →  baja trades, arma velas          collector.py, exchange/bitso.py
storage    →  SQLite: trades, velas, journal   storage.py
strategy   →  función pura (velas) → señal     strategy/
risk       →  veto duro, kill switch           risk.py
broker     →  paper | live, misma interfaz     broker/
backtest   →  historia cerrada, una pasada     backtest.py
paper      →  velas que van cerrando, en vivo  paper.py
phase      →  criterio de salida de la fase    phase.py
metrics    →  desempeño, siempre neto          metrics.py

api        →  lectura del journal (FastAPI)     services/api/
web        →  landing + dashboard (nginx)       services/web/
```

Cuatro decisiones que valen la pena explicar:

**La estrategia es una función pura.** Recibe la historia de velas y devuelve
una señal. No conoce el capital, no accede a la red, no guarda estado. Eso la
hace testeable y elimina por construcción el look-ahead bias (hay un test que
lo verifica).

**El tamaño de posición no es decisión de la estrategia.** Es de `risk.py`, la
única capa con poder de veto. Un bug en la estrategia no puede convertirse en
una pérdida total.

**Paper y vivo comparten todo menos `execute()`.** Es la garantía de que lo
validado en papel es literalmente el mismo código que correrá con plata real.

**El journal registra cada decisión, incluidos los rechazos.** Un rechazo
silencioso es un backtest que miente. Durante el desarrollo esto ya encontró un
bug real: el sizing calculaba la cantidad contra el precio de referencia sin
descontar spread ni comisión, la orden salía más cara que el efectivo
disponible y el broker la rechazaba sin registrar nada.

## Seguridad

Reglas no negociables:

1. **La API key se crea con permisos de solo lectura.** Trading se agrega recién
   en Fase 2. Retiros, nunca.
2. **Las credenciales van en variables de entorno.** Nunca en el código, nunca
   en el repo, nunca pegadas en un chat.
3. **El bot arranca siempre en papel** (`Config.live_trading = False`). Pasar a
   real es un cambio explícito y manual.
4. **El kill switch no se rearma solo.** Requiere intervención humana. Un bot
   que se reactiva después de perder es un bot que insiste en perder.
5. **Este contenedor no es un host de producción.** Es efímero. El bot va a un
   VPS con IP fija, que además permite whitelistear la IP en Bitso.

## Limitaciones conocidas

- El broker de papel asume llenado completo al precio efectivo. No modela
  órdenes parcialmente llenas ni rechazos del exchange, así que sus resultados
  son una **cota superior** de lo alcanzable en vivo.
- Los defaults de `CostModel` son estimaciones conservadoras, no las comisiones
  reales de tu cuenta. Correr `calibrate` antes de confiar en cualquier
  resultado.
- `SmaCross` es una baseline de referencia, no una estrategia recomendada.
  Está para que cualquier idea nueva tenga contra qué medirse — junto con
  `BuyAndHold`, que le gana más seguido de lo cómodo.
- Sin datos reales acumulados, todo resultado de este repo es sobre datos
  sintéticos y no dice nada sobre rentabilidad.

## Descargo

Esto es software para aprender y medir, no asesoramiento financiero. Operar
criptomonedas puede resultar en la pérdida total del capital. Las implicancias
impositivas son responsabilidad de quien opera.
