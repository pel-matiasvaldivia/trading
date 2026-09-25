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

**3. Configurar el entorno.**

```bash
mkdir -p /opt/tradingbot && cd /opt/tradingbot
curl -O https://raw.githubusercontent.com/pel-matiasvaldivia/trading/main/deploy/docker-compose.yml
curl -o .env https://raw.githubusercontent.com/pel-matiasvaldivia/trading/main/deploy/.env.example
openssl rand -hex 32   # pegar el resultado en DASHBOARD_TOKEN
nano .env
chmod 600 .env
```

`DASHBOARD_TOKEN` es obligatorio: sin él el compose se niega a levantar. Es la
única barrera entre internet y tus datos de trading.

## Levantar

```bash
docker compose pull
docker compose up -d
docker compose ps
docker compose logs -f collector
```

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

Solo se publica `web`. La API y el collector quedan en la red interna y no son
alcanzables desde afuera: el navegador llega a `/api/` porque `web` hace de
proxy hacia adentro.

Si NPM no ve el contenedor, es que no comparten red — revisá `PROXY_NETWORK`.

## Actualizar

```bash
docker compose pull && docker compose up -d
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
- **La API nunca se expone**. Aunque alguien adivine el token, tendría que
  estar dentro de la red Docker.

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
curl -s https://tu-dominio/api/health
curl -s -H "X-API-Token: $DASHBOARD_TOKEN" https://tu-dominio/api/status
```

El primero responde sin token (lo usa el healthcheck de Docker). El segundo sin
token debe dar **401** — si da 200, `DASHBOARD_TOKEN` no llegó al contenedor.
