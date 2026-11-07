<div align="center">

[🇷🇺 Русский](README.md) · [🇬🇧 English](README.en.md) · [🇪🇬 العربية](README_AR.md) · [🇮🇷 فارسی](README_FA.md) · [🇨🇳 简体中文](README_ZH_CN.md) · 🇪🇸 **Español** · [🇹🇷 Türkçe](README_TR.md)

<h1 align="center"><img src="assets/branding/logo.png" alt="Telegram Web Proxy Manager" width="560"></h1>

### Tu propio proxy Telegram WEB con HTTPS y un sitio de camuflaje completo

**TELEMT · NGINX · HTTPS · SITIO DE CAMUFLAJE · SOCKS5 · ACTUALIZACIONES SEGURAS**

Un VPS, un dominio exclusivo y un enlace listo para conectar Telegram.

[![Pruebas](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml/badge.svg)](https://github.com/xPROMSx/telegram-web-proxy-manager/actions/workflows/checks.yml)
![Ubuntu](https://img.shields.io/badge/Ubuntu-24.04%20%7C%2026.04-E95420?logo=ubuntu&logoColor=white)
[![Versión](https://img.shields.io/github/v/release/xPROMSx/telegram-web-proxy-manager)](https://github.com/xPROMSx/telegram-web-proxy-manager/releases/latest)

[📦 Versiones](https://github.com/xPROMSx/telegram-web-proxy-manager/releases) · [⚙️ 3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx) · [❤️ Apoyar](#support-development) · [🐛 Informar de un problema](https://github.com/xPROMSx/telegram-web-proxy-manager/issues) · [💬 Comunidad](https://t.me/promsdev)

</div>

**Telegram Web Proxy Manager (TWPM)** es un gestor gratuito para instalar y mantener tu propio proxy Telegram WEB en un VPS. Utiliza [Telemt](https://github.com/telemt/telemt) como motor y Nginx para ofrecer HTTPS, enrutamiento por dominio y un sitio de camuflaje. El gestor configura los componentes necesarios, obtiene un certificado Let's Encrypt y muestra un enlace listo para añadir el proxy a Telegram.

**Mucho más que instalar Telemt:** cada instalación nueva recibe un sitio web original de varias páginas y apariencia personalizada. En vez de necesitar otro servidor web, utiliza el Nginx ya instalado; el proxy, los certificados y el sitio se administran conjuntamente.

TWPM y [**3X-UI AUTO NGINX**](https://github.com/xPROMSx/3x-ui-auto-nginx) son dos proyectos de xPROMSx desarrollados para funcionar juntos. Pueden compartir un VPS y un mismo Nginx, mientras cada uno gestiona sus ajustes, certificados y servicios de forma independiente. **TWPM también funciona con otras configuraciones compatibles de Nginx**: no es obligatorio instalar 3X-UI.

## ✨ Características

| | |
| --- | --- |
| **Sitio de camuflaje completo**<br>Tres temáticas originales, varias páginas, navegación funcional, ilustraciones y diseño adaptado a móviles. | **Instalaciones personalizadas**<br>El nombre, la paleta de colores, los textos y las imágenes se seleccionan al crear el sitio. |
| **HTTPS mediante Nginx**<br>Dominio exclusivo, Let's Encrypt, enrutamiento SNI y convivencia con otros servicios en TCP/443. | **Integración con 3X-UI AUTO NGINX**<br>Instala o abre el proxy de Telegram desde el menú del proyecto complementario sin sustituir sus conexiones. |
| **Actualizaciones seguras de Telemt**<br>Búsqueda de versiones oficiales, verificación de autenticidad y funcionamiento, y conservación de la versión anterior operativa. | **Conservación de la instalación**<br>El mantenimiento habitual no sustituye ajustes, claves, datos, certificados ni el sitio. |
| **Conexión directa o SOCKS5**<br>Elige cómo accede el VPS a Telegram si la conexión directa no está disponible. | **Gestión sencilla**<br>Menús en ruso e inglés para instalar, actualizar, comprobar, reparar, mostrar enlaces y desinstalar. |

<a id="quick-start"></a>

## 🚀 Inicio rápido

Necesitas un **VPS con Ubuntu 24.04 o 26.04**, acceso **root**, Nginx en funcionamiento con una configuración SNI compatible y **un dominio o subdominio exclusivo**. Su registro DNS A debe apuntar a la IPv4 pública del VPS. El puerto TCP/80 debe ser accesible para obtener el certificado HTTPS y el TCP/443 para las conexiones del proxy.

> [!IMPORTANT]
> El dominio del proxy de Telegram debe estar **libre**. No reutilices el dominio del panel de 3X-UI, REALITY, Vision ni de otro sitio existente en Nginx.

**Si ya tienes instalado 3X-UI AUTO NGINX**, abre su menú principal y selecciona **4 — Telegram Web Proxy Manager**. Desde ahí puedes instalar TWPM o ejecutar la instalación existente.

**Para instalarlo de forma independiente** en un VPS con Nginx compatible, ejecuta como root:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/xPROMSx/telegram-web-proxy-manager/main/install.sh)
```

Al iniciar, selecciona **1 — English** o **2 — Русский**. La interfaz del gestor solo está disponible en esos dos idiomas. Después aparecerá el menú principal (se muestran los nombres reales de las opciones en inglés):

- **1 — Install Telegram proxy:** instalación nueva o comprobación de una instalación existente sin reinstalarla.
- **2 — Update Telemt:** buscar e instalar de forma segura una actualización del motor.
- **3 — Check status:** comprobar el funcionamiento sin modificar la configuración.
- **4 — Check and restart services:** validar la configuración, reiniciar Telemt y recargar Nginx.
- **5 — Show connection link:** volver a mostrar el enlace del proxy para Telegram.
- **6 — Uninstall Telegram proxy:** eliminar la instalación administrada, previa confirmación.
- **0 — Exit:** salir.

Para la primera instalación, elige **1 — Install Telegram proxy**. El gestor te pedirá, por este orden:

1. **WEB proxy domain (dominio del proxy WEB).** Introduce tu dominio o subdominio exclusivo, previamente preparado y libre.
2. **Public IPv4 (IPv4 pública).** El gestor intentará detectar automáticamente la dirección IP del VPS. Compárala con la IPv4 del servidor y con el registro DNS A del dominio. Si es correcta, pulsa simplemente **Enter**. Si no se detecta o es incorrecta, introduce la dirección correcta manualmente.
3. **Use SOCKS5 upstream? [y/N] (¿usar SOCKS5?)** SOCKS5 es un proxy intermediario opcional a través del cual el VPS puede acceder a los servidores de Telegram. **Si tu VPS accede directamente a Telegram, no necesitas SOCKS5: pulsa Enter o elige N.** Si no hay acceso directo, configura primero un proxy SOCKS5 funcional *antes de la instalación*; después elige **Y** e introduce su dirección y puerto. **¿No sabes qué es SOCKS5? Elige N.**

Al terminar, el gestor configurará HTTPS y el sitio de camuflaje y mostrará un enlace `tg://webproxy?...` listo para añadir el proxy a Telegram.

Para administrarlo más adelante, ejecuta:

```bash
telegram-web-proxy-manager
```

> [!CAUTION]
> El enlace de Telegram contiene la clave privada de acceso a tu proxy. No lo publiques ni lo compartas con otras personas.

## 🌐 Sitios de camuflaje y Nginx

**Un sitio completo en lugar de una simple página de relleno.** En cada instalación nueva, TWPM crea automáticamente uno de estos tres diseños originales:

- **Botanical Journal** — revista sobre plantas.
- **Night Sky Guide** — guía del cielo nocturno.
- **Home Kitchen** — sitio de cocina casera.

Cada diseño contiene **11 archivos locales**, con varias páginas, estilos e ilustraciones. El sitio se adapta a dispositivos móviles, no necesita recursos externos y recibe un aspecto personalizado. El diseño se conserva durante las actualizaciones y el mantenimiento; los sitios de instalaciones anteriores no se sustituyen.

**El sitio y el proxy funcionan mediante el Nginx ya instalado.** No hace falta Docker ni otro servidor web.

## 🤝 Integración con 3X-UI AUTO NGINX

**Dos proyectos independientes, una infraestructura compatible.** [3X-UI AUTO NGINX](https://github.com/xPROMSx/3x-ui-auto-nginx) instala y administra 3X-UI/Xray y la configuración compartida de Nginx. **Telegram Web Proxy Manager** añade un proxy Telegram WEB independiente utilizando el enrutamiento compatible de Nginx y su propio dominio.

- **Orden recomendado:** instala primero 3X-UI AUTO NGINX y después TWPM. El primer proyecto instala Nginx; TWPM no lo instala.
- **Uso compartido de TCP/443:** el enrutamiento SNI permite alojar los servicios en un mismo VPS sin sustituir las rutas existentes de 3X-UI.
- **Mantenimiento independiente:** TWPM administra sus propios Telemt, sitio y certificados sin asumir el control de la configuración ni los datos de 3X-UI.
- **Compatibilidad con Backup v3:** el 3X-UI AUTO NGINX actual reconoce las configuraciones habituales de TWPM. Sin embargo, el Backup de 3X-UI **no sustituye una copia de seguridad de los datos propios de Telemt**.

**También se admiten otras configuraciones de Nginx** que cumplan los patrones stream/SNI conocidos por TWPM, incluidas algunas con archivos `include` independientes. El gestor no reconfigura cualquier instalación de Nginx: rechaza de forma segura los patrones desconocidos o conflictivos. [Requisitos técnicos](docs/OPERATIONS.md#nginx-requirements).

> [!IMPORTANT]
> TWPM admite **Ubuntu 24.04 y 26.04**. Que 3X-UI AUTO NGINX admita Debian no significa que Telegram Web Proxy Manager también lo admita.

## 🔄 Actualizaciones y mantenimiento

En la primera instalación, el gestor despliega una versión verificada de Telemt. **Universal Update** busca por separado la última versión estable oficial compatible y la valida antes del cambio. Si una actualización falla, existe un mecanismo para recuperar la versión anterior funcional y conservar el estado.

Actualizar **TWPM** y actualizar **Telemt** son operaciones independientes. El mantenimiento habitual no vuelve a crear el sitio, no restablece claves secretas ni migra instalaciones antiguas a otra configuración sin consentimiento.

Las comprobaciones de estado están disponibles en el menú y, cuando hace falta, es posible reparar instalaciones compatibles. La eliminación solo afecta a elementos cuya pertenencia al gestor se ha verificado; borrar certificados requiere una confirmación aparte.

## ⚙️ Requisitos y pruebas

- **Sistema:** Ubuntu 24.04 / 26.04, x86_64 o ARM64; acceso root y systemd.
- **Red:** dominio o subdominio exclusivo, registro DNS A correcto y acceso a los puertos TCP necesarios.
- **Nginx:** configuración stream/SNI compatible y ya existente. El gestor no instala Nginx, 3X-UI ni Xray, ni modifica las reglas del cortafuegos del sistema.
- **Telemt:** lo instala TWPM; la versión base verificada para instalaciones nuevas es la **3.5.16** y Universal Update funciona por separado.

El proyecto pasa pruebas automatizadas y de integración en las versiones de Ubuntu admitidas, incluidas pruebas reales de Nginx y Telemt. Las configuraciones no estándar de Nginx requieren una verificación de compatibilidad independiente. [Cobertura y limitaciones de las pruebas](docs/CI-COVERAGE.md).

## 📖 Documentación

- [Funcionamiento, compatibilidad con Nginx y recuperación](docs/OPERATIONS.md)
- [Cobertura y limitaciones de las pruebas](docs/CI-COVERAGE.md)
- [Fuentes de Telemt y seguridad de las actualizaciones](docs/UPSTREAM.md)
- [Licencia GPL-3.0](LICENSE)

## 💬 Comunidad y comentarios

Sigue las novedades de los proyectos xPROMSx en el [canal de Telegram @promsdev](https://t.me/promsdev). Envía preguntas e ideas mediante los [mensajes al canal](https://t.me/promsdev?direct) y notifica errores en [GitHub Issues](https://github.com/xPROMSx/telegram-web-proxy-manager/issues).

<a id="support-development"></a>

## ❤️ Apoyar el desarrollo

Telegram Web Proxy Manager es gratuito y está disponible para todos. Si te ha resultado útil, puedes [apoyar voluntariamente su desarrollo](docs/SUPPORT_ES.md). Las donaciones no afectan al acceso a ninguna función.

<div align="center">

**Tu propio proxy de Telegram. HTTPS seguro. Un sitio de camuflaje completo.**

⭐ Si el proyecto te parece útil, [dale una Star](https://github.com/xPROMSx/telegram-web-proxy-manager) para ayudar a que otros lo descubran.

[Instalación](#quick-start) · [Versiones](https://github.com/xPROMSx/telegram-web-proxy-manager/releases) · [Problemas](https://github.com/xPROMSx/telegram-web-proxy-manager/issues)

</div>
