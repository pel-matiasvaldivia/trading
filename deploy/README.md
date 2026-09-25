# Despliegue en el VPS

El VPS no compila nada. GitHub Actions construye las imágenes y las publica en
GHCR; acá solo se hace `pull` y `up`.

## Supuesto sobre "NPM"

Este stack asume que **NPM = Nginx Proxy Manager**, el reverse proxy que ya
corre en el VPS y termina TLS. Por eso ningún servicio publica puertos al host:
se exponen en la red Docker de NPM y este los enruta.

Si en tu caso NPM significaba otra cosa (el gestor de paquetes de Node), avisá:
cambia el bloque `networks` del compose, no el resto del stack.

## Preparación

**1. Hacer públicos los paquetes, o autenticar el pull.**

Los paquetes de GHCR nacen privados. O los hacés públicos desde la página del
paquete en GitHub (Package settings → Change visibility), o autenticás el VPS:

```bash
echo "$GHCR_TOKEN" | docker login ghcr.io -u <tu-usuario> --password-stdin
```

El token necesita solo el scope `read:packages`.

**2. Averiguar el nombre de la red de NPM.**

```bash
docker network ls | grep -i proxy
```

Suele llamarse `npm_default` o similar. Ese valor va en `PROXY_NETWORK`.

**3. Clonar el repo y configurar el entorno.**

El `docker-compose.yml` y el `.env.example` están en la raíz del repo, así que
el VPS se actualiza con `git pull`:

```bash
git clone https://github.com/pel-matiasvaldivia/trading.git /opt/tradingbot
cd /opt/tradingbot
cp .env.example .env
openssl rand -hex 32   # pegar el resultado en DASHBOARD_TOKEN
nano .env
chmod 600 .env
```

`.env` está en `.gitignore`, así que un `git pull` nunca lo pisa.

`DASHBOARD_TOKEN` es obligatorio: sin él el compose se niega a levantar. Es la
única barrera entre internet y tus datos de trading.

Hay un solo `.env.example` y cubre las dos formas de correr el proyecto: el bot
local y el stack Docker. Cada sección aclara cuál usa qué. La única variable
que difiere es `TRADING_DB_PATH`, y en Docker la fija el compose
(`/data/trading.db`, sobre el volumen), así que el valor del `.env` solo aplica
cuando corrés el bot fuera de contenedores.

## Levantar

```bash
docker compose pull
docker compose up -d
docker compose ps
docker compose logs -f collector
```

## Fase 1: paper trading

El collector corre el motor de papel después de cada ciclo de recolección,
dentro del mismo proceso. Se controla por `.env`:

| Variable | Default | Qué es |
|---|---|---|
| `PAPER_ENABLED` | `1` | `0` para solo recolectar, sin operar en papel |
| `PAPER_TF` | `1h` | timeframe de las velas sobre las que opera |
| `PAPER_FAST` / `PAPER_SLOW` | `10` / `30` | medias de la estrategia baseline |

**Las tres últimas las lee también la API.** Si difieren entre el collector y
la API, el dashboard evaluaría una corrida distinta de la que realmente está
operando. El compose las pasa a ambos servicios desde el mismo `.env`, así que
no pueden desincronizarse salvo que las edites a mano.

Seguimiento:

```bash
docker compose logs -f collector                      # ciclos y fills
docker compose exec api python -m tradingbot gate     # veredicto de la fase
```

El veredicto también está arriba de todo en el dashboard, con cuántas
operaciones faltan y una estimación de cuánto hay que esperar.

**Calibrar los costos.** Mientras no haya mediciones, el panel marca los costos
como `ESTIMADO` y el criterio de fase se evalúa contra supuestos:

```bash
docker compose exec api python -m tradingbot calibrate --book usd_ars
```

Conviene correrlo varias veces al día — el modelo usa la mediana de las
muestras, porque el spread se abre y se cierra y una sola lectura puede caer
justo en el mejor momento.

## Puertos publicados

El stack publica dos puertos en el host, ambos configurables desde `.env`:

| Variable | Default | Qué es |
|---|---|---|
| `WEB_PORT` | `8080` | frontend; sirve también `/api` vía nginx |
| `WEB_BIND` | `0.0.0.0` | interfaz donde se publica el frontend |
| `API_PORT` | `8000` | API directa, sin pasar por nginx |
| `API_BIND` | `127.0.0.1` | interfaz donde se publica la API |

Con los defaults, después de `up -d`:

```bash
curl http://localhost:8080/api/health          # frontend + API
curl http://localhost:8000/api/health          # API directa, solo desde el VPS
```

Y desde afuera, `http://IP-DEL-VPS:8080`.

**Lo que hay que entender sobre `WEB_BIND=0.0.0.0`:** publica el dashboard en
todas las interfaces, incluida la pública, **sin el TLS de NPM**. El tráfico va
en claro y el `DASHBOARD_TOKEN` viaja en un header sin cifrar, así que
cualquiera en el camino puede leerlo y entrar.

Hay tres configuraciones sensatas, según para qué lo quieras:

- **NPM al frente (recomendado).** `WEB_BIND=127.0.0.1`. NPM llega al
  contenedor por la red Docker, no por este puerto; el puerto local queda
  solo para diagnóstico. Tenés TLS y el token nunca viaja en claro.
- **Acceso directo temporal, para probar.** `WEB_BIND=0.0.0.0`. Funciona ya
  mismo, sin configurar NPM. Cerralo cuando termines.
- **Acceso directo permanente.** `WEB_BIND=0.0.0.0` más una regla de firewall
  que limite el puerto a tu IP (`ufw allow from TU_IP to any port 8080`).

El default es `0.0.0.0` porque pediste acceso externo y así funciona sin
configurar nada más. Si vas a usar NPM, cambialo a `127.0.0.1`.

Si el puerto 8080 ya está ocupado en el VPS (`ss -lntp | grep 8080`), cambiá
`WEB_PORT` y listo.

## Conectar Nginx Proxy Manager

En la interfaz de NPM, **Proxy Hosts → Add Proxy Host**:

| Campo | Valor |
|---|---|
| Domain Names | el dominio que vayas a usar |
| Scheme | `http` |
| Forward Hostname | `tradingbot-web-1` (o el nombre que muestre `docker ps`) |
| Forward Port | `80` |
| Block Common Exploits | sí |
| Websockets Support | no hace falta |

En la pestaña **SSL**: pedir certificado Let's Encrypt y activar *Force SSL* y
*HTTP/2*.

Al usar NPM conviene poner `WEB_BIND=127.0.0.1`: NPM alcanza el contenedor por
la red Docker, así que el puerto del host no hace falta y dejarlo abierto sería
una puerta paralela sin TLS.

El collector nunca se publica. La API se publica solo en loopback por defecto,
para diagnóstico: el navegador llega a `/api/` porque `web` hace de proxy hacia
adentro, no por el puerto 8000.

Si NPM no ve el contenedor, es que no comparten red — revisá `PROXY_NETWORK`.

## Actualizar

```bash
cd /opt/tradingbot
git pull
docker compose pull && docker compose up -d
```

`git pull` trae los cambios del compose; `docker compose pull` trae las
imágenes nuevas. Si sale una variable nueva en `.env.example`, compará con tu
`.env`:

```bash
diff <(grep -oE '^[A-Z_]+=' .env.example | sort) <(grep -oE '^[A-Z_]+=' .env | sort)
```

`IMAGE_TAG=latest` sigue a `main`. En producción conviene fijar un tag
inmutable (`sha-<commit>` o `v1.2.3`) para que un redeploy no traiga cambios
que no revisaste.

## Arquitectura del stack

```
internet → NPM (TLS) → web:80 ──┬── estáticos (landing + dashboard)
                                └── /api/ → api:8000 (solo red interna)

collector ──escribe──→ volumen trading-data ──lee (ro)──→ api
```

Tres decisiones de seguridad que vale la pena notar:

- **El collector es el único que escribe** y el único que recibe las
  credenciales de Bitso. La API monta el volumen con `:ro` y además abre SQLite
  en modo solo lectura: dos candados independientes.
- **Todos los contenedores corren con `read_only: true`**, sin privilegios
  nuevos (`no-new-privileges`) y con usuario sin root.
- **La API se publica solo en loopback** (`API_BIND=127.0.0.1`). Desde fuera
  del VPS no es alcanzable; desde adentro sirve para diagnosticar con curl.

## Rendimiento de las imágenes

| Medida | Por qué |
|---|---|
| Multi-stage | las herramientas de build no viajan al runtime |
| `python:3.11-slim` | base mínima sin compiladores |
| venv copiado desde el builder | una sola capa, sin caché de pip |
| Dependencias antes que el código | cambiar Python no invalida la capa de deps |
| `compileall` en build | el arranque no paga la compilación a bytecode |
| Una imagen para api y collector | comparten capas: un pull, no dos |
| `uvloop` + `httptools` | el camino rápido de uvicorn |
| gzip y brotli en build, `gzip_static` | el VPS no recomprime en cada request |
| Sin bundler ni framework en el front | no hay JS que no sea el que escribiste |
| Caché de registry + GHA en buildx | builds incrementales entre ramas |

`linux/arm64` se construye bajo emulación QEMU y duplica el tiempo del
workflow. Si el VPS es x86, borrá esa plataforma de `.github/workflows/images.yml`.

## Verificación

```bash
# Por el puerto publicado
curl -s http://localhost:${WEB_PORT:-8080}/api/health
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:${WEB_PORT:-8080}/api/status

# Por NPM, si ya lo configuraste
curl -s https://tu-dominio/api/health
curl -s -H "X-API-Token: $DASHBOARD_TOKEN" https://tu-dominio/api/status
```

El primero responde sin token (lo usa el healthcheck de Docker). El segundo sin
token debe dar **401** — si da 200, `DASHBOARD_TOKEN` no llegó al contenedor.
