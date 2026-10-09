<div align="center">

[🇷🇺 Русский](README.md) · [🇬🇧 English](README.en.md) · [🇪🇬 العربية](README_AR.md) · [🇮🇷 فارسی](README_FA.md) · [🇨🇳 简体中文](README_ZH_CN.md) · 🇪🇸 **Español** · [🇹🇷 Türkçe](README_TR.md)

<h1 align="center">Telegram Web Proxy Manager</h1>

### Tu propio proxy de Telegram en un VPS, sin configuración manual

**HTTPS · Sitio de camuflaje · SOCKS5 · Actualizaciones seguras**

Conexión directa a los servidores de Telegram o mediante SOCKS5.

[![Pruebas](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml/badge.svg)](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04%20%7C%2026.04-E95420?logo=ubuntu&logoColor=white)
[![Versiones](https://img.shields.io/github/v/release/xPROMSx/telegram-web-proxy-manager)](https://github.com/xPROMSx/telegram-web-proxy-manager/releases/latest)

[Versiones](https://github.com/xPROMSx/telegram-web-proxy-manager/releases) · [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx) · [Informar de un problema](https://github.com/xPROMSx/telegram-web-proxy-manager/issues)

</div>

**Telegram Web Proxy Manager** instala y configura un proxy Telegram WEB, permite acceder a él mediante HTTPS seguro y despliega automáticamente un sitio de camuflaje en tu dominio. Si el VPS no puede acceder directamente a Telegram, puedes utilizar un proxy SOCKS5 como conexión de salida.

Al actualizar Telemt, el gestor verifica la nueva versión y restaura la última versión funcional si alguna comprobación falla.

**Compatibilidad:** la batería completa de pruebas de integración incluye la convivencia con [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx). [Cobertura y límites de las pruebas](docs/CI-COVERAGE.md).

## ✨ Funciones

- Instalación y configuración del proxy de Telegram con un solo comando.
- HTTPS seguro con certificado de Let's Encrypt.
- Sitio de camuflaje desplegado automáticamente en el dominio.
- Actualizaciones seguras con restauración de la versión anterior si se produce un error.
- Conexión directa a Telegram o mediante un proxy SOCKS5.
- Comprobaciones del estado y la conectividad del proxy.

## 🚀 Inicio rápido

Necesitas un VPS con **Ubuntu 24.04 o 26.04**, acceso **root**, Nginx ya configurado de forma compatible y **un dominio o subdominio independiente** cuyo registro DNS A apunte a la IPv4 pública del servidor. Este nombre **no debe estar en uso por 3X-UI (incluido REALITY) ni por otro sitio de Nginx**.

Si todavía no has preparado el servidor, puedes instalar primero [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx).

Ejecuta como root:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/xPROMSx/telegram-web-proxy-manager/main/install.sh)
```

En el menú interactivo, elige **Install** y sigue las indicaciones. Cuando termine la instalación, recibirás un enlace `tg://webproxy?...` para añadir el proxy a Telegram. El dominio mostrará un sitio de camuflaje por HTTPS.

Para administrar el proxy después, ejecuta `telegram-web-proxy-manager`.

> **Importante:** el enlace de conexión contiene la clave de acceso al proxy. No lo publiques.

## 🤝 Uso conjunto con 3X-UI AUTO NGINX

Si también necesitas **3X-UI** y Xray en el VPS, utiliza [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx), que prepara Nginx, HTTPS y la configuración de 3X-UI.

**Orden de instalación:** primero 3X-UI AUTO NGINX y después Telegram Web Proxy Manager. Ambos proyectos pueden funcionar en el mismo VPS y gestionan sus servicios y certificados de forma independiente. Telegram necesita **su propio dominio o subdominio libre**.

## Qué utiliza internamente

El proxy se basa en [Telemt](https://github.com/telemt/telemt). El gestor lo instala, configura y actualiza automáticamente; no hace falta instalar Telemt por separado.

## Requisitos y pruebas

- **Ubuntu 24.04 o 26.04** y acceso **root**.
- Dominio o subdominio independiente con un registro DNS A hacia la IPv4 pública del VPS, no utilizado por 3X-UI / REALITY ni por otro sitio de Nginx.
- Nginx en funcionamiento con una [configuración compatible](docs/OPERATIONS.md).

El proyecto cuenta con pruebas automatizadas, incluida la integración con Nginx y la compatibilidad con 3X-UI AUTO NGINX. Consulta la [cobertura y limitaciones](docs/CI-COVERAGE.md).

## Documentación

- [Operación y recuperación](docs/OPERATIONS.md)
- [Cobertura y límites de las pruebas](docs/CI-COVERAGE.md)
- [Fuentes de Telemt y verificación de versiones](docs/UPSTREAM.md)
- [Licencia GPL-3.0](LICENSE)
