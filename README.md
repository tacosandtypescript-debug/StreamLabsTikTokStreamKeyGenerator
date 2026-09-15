# Generador de clave de directo de TikTok para OBS (vía Streamlabs)

[![Pruebas](https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/actions/workflows/test.yml/badge.svg)](https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/actions/workflows/test.yml)
[![Compilación y publicación](https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/actions/workflows/release.yml/badge.svg)](https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/actions/workflows/release.yml)
[![Última versión](https://img.shields.io/github/v/release/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator?label=descarga)](https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/releases/latest)
[![Licencia](https://img.shields.io/badge/licencia-GPL--3.0-blue)](LICENSE.txt)

Aplicación de escritorio (PySide6) que **prepara una sesión RTMP de TikTok Live
a través de Streamlabs y te da la URL del servidor y la clave de retransmisión**
para pegarlas en OBS Studio o en cualquier otro programa de emisión.

> **Importante:** la aplicación **no emite vídeo** ni configura OBS por ti. Lo
> que hace es pedirle a Streamlabs que prepare la sesión; la emisión empieza
> cuando OBS se conecta con esos datos.

## ⬇️ Instalación fácil

| | |
|---|---|
| **[Descargar la última versión](https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/releases/latest)** | El ZIP de tu sistema + `SHA256SUMS.txt` |
| [Todas las versiones](https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/releases) | Historial completo |
| [Compilaciones automáticas](https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/actions/workflows/release.yml) | Ver el estado y descargar artefactos de una compilación concreta |
| [Estado de las pruebas](https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/actions/workflows/test.yml) | Ubuntu, Windows y macOS |

Los binarios se compilan **automáticamente** en GitHub Actions: no hay que
compilar nada a mano. Sigue leyendo para elegir tu archivo y verificar que la
descarga es íntegra.

Este repositorio es una versión endurecida (y traducida) del proyecto original
de [Loukious](https://github.com/Loukious/StreamLabsTikTokStreamKeyGenerator).
Ver [Atribución y licencia](#atribución-y-licencia).

---

## Índice

- [Qué necesitas antes de empezar](#qué-necesitas-antes-de-empezar)
- [Descarga e instalación](#descarga-e-instalación)
- [Uso paso a paso](#uso-paso-a-paso)
- [Cómo emitir en OBS](#cómo-emitir-en-obs)
- [Dónde se guarda tu token (seguridad)](#dónde-se-guarda-tu-token-seguridad)
- [Actualizaciones](#actualizaciones)
- [Problemas frecuentes](#problemas-frecuentes)
- [Ejecutar desde el código fuente](#ejecutar-desde-el-código-fuente)
- [Publicar una versión nueva](#publicar-una-versión-nueva-mantenedor)
- [Avisos y limitaciones](#avisos-y-limitaciones)
- [Atribución y licencia](#atribución-y-licencia)

---

## Qué necesitas antes de empezar

1. **Una cuenta de TikTok con acceso a TikTok LIVE vía Streamlabs.** Es un
   programa con aprobación: si tu cuenta no lo tiene, esta aplicación no puede
   hacer nada. Se solicita aquí:
   <https://tiktok.com/falcon/live_g/live_access_pc_apply/result/index.html?id=GL6399433079641606942&lang=en-US>
   *(No hace falta tener 1.000 seguidores para pedirlo.)*
2. **Windows, macOS o Linux.**
3. **Un navegador** para la opción de inicio de sesión web.
4. *(Opcional)* **Streamlabs Desktop instalado y con sesión iniciada en TikTok**,
   solo si quieres usar el botón «Cargar desde el PC».
5. *(Solo Linux)* El paquete **`libsecret`** si quieres que el token se guarde
   cifrado. Sin él, el token solo dura lo que dure la aplicación abierta.

---

## Descarga e instalación

### Opción A — Usar la versión compilada (recomendado)

⬇️ **<https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/releases/latest>**

1. Entra en ese enlace (o en la pestaña **[Releases](../../releases/latest)** del
   repositorio).
2. Descarga el archivo que corresponda a tu sistema:
   - `...-win-<versión>.zip` → **Windows**
   - `...-arm64-macos-<versión>.zip` → **macOS con Apple Silicon** (M1/M2/M3…)
   - `...-x86_64-macos-<versión>.zip` → **macOS con Intel**
   - `...-linux-<versión>.zip` → **Linux**
3. **Comprueba el checksum** (recomendado, 10 segundos). Abre `SHA256SUMS.txt` en
   la misma página de la release y compara el valor de tu archivo con su línea:

   ```powershell
   # Windows
   Get-FileHash .\StreamLabsTikTokStreamKeyGenerator-win-2.1.0.zip -Algorithm SHA256
   ```
   ```bash
   # macOS
   shasum -a 256 StreamLabsTikTokStreamKeyGenerator-x86_64-macos-2.1.0.zip
   # Linux
   sha256sum StreamLabsTikTokStreamKeyGenerator-linux-2.1.0.zip
   ```

   Si descargas **todos** los ZIP en una misma carpeta junto a `SHA256SUMS.txt`,
   en Linux puedes verificarlos de una sola vez:

   ```bash
   sha256sum -c --ignore-missing SHA256SUMS.txt
   ```

   El hash debe coincidir exactamente con su línea del archivo. Si no coincide,
   **no lo ejecutes**: vuelve a descargarlo.
4. Descomprime el ZIP y ejecuta la aplicación.

**Notas por sistema:**

- **Windows:** el binario no está firmado, así que SmartScreen puede avisar
  («Windows protegió tu PC»). Pulsa *Más información → Ejecutar de todas formas*
  solo si el checksum coincide.
- **macOS:** Gatekeeper puede decir que la aplicación «está dañada o está
  incompleta». **No desactives Gatekeeper a ciegas**; si el checksum es correcto,
  puedes quitar la cuarentena del archivo que descargaste:

  ```bash
  xattr -dr com.apple.quarantine /ruta/a/StreamLabsTikTokStreamKeyGenerator.app
  ```
- **Linux:** si al guardar el token te dice que no hay almacén seguro, instala
  `libsecret` (`sudo apt install libsecret-1-0` en Debian/Ubuntu).

### Opción B — Ejecutar desde el código fuente

Ver [Ejecutar desde el código fuente](#ejecutar-desde-el-código-fuente).

---

## Uso paso a paso

### 1. Abre la aplicación

### 2. Consigue el token de Streamlabs

Tienes tres formas. Elige **una**:

| Método | Cuándo usarlo | Qué hace |
|---|---|---|
| **Load from Web** | Lo normal, y lo recomendado | Abre tu navegador, inicias sesión en Streamlabs y la aplicación recibe el token sola (OAuth con PKCE). |
| **Load from PC** | Si ya usas Streamlabs Desktop | Lee el token que Streamlabs Desktop tiene guardado en tu equipo. Solo Windows y macOS. |
| **Pegar el token** | Si ya lo tienes a mano | Pégalo en el campo *Paste token here*. |

Con **Load from Web**: se abrirá una pestaña del navegador, inicias sesión en
Streamlabs con tu cuenta de TikTok y, cuando termine, puedes cerrar esa pestaña.
La aplicación recibe el token automáticamente.

Con **Load from PC**: no necesitas navegador, pero **lee datos de otra
aplicación** (Streamlabs Desktop). Es legítimo en tu propio equipo, aunque
algunos antivirus se ponen nerviosos con eso; si te pasa, usa *Load from Web*.

### 3. Valida la cuenta

Pulsa **Refresh Account Info**. Verás arriba rellenados:

- **Username:** tu usuario de TikTok.
- **Status:** el estado de tu solicitud de acceso.
- **Can Go Live:** `True` o `False`.

Si pone `False`, tu cuenta todavía no tiene permiso de emisión: **el botón Go
Live quedará bloqueado**, porque TikTok rechazaría el directo igualmente.

### 4. Guarda el token (opcional pero cómodo)

Pulsa **Save Token Securely**. El token se guarda **cifrado en el almacén de
credenciales de tu sistema** (Administrador de credenciales de Windows, Llavero
de macOS, Secret Service en Linux), así que la próxima vez la aplicación arranca
ya con la sesión puesta y no tienes que volver a iniciar sesión.

### 5. Rellena el directo

- **Stream Title:** el título del directo.
- **Game Category:** empieza a escribir y elige una de las sugerencias que
  aparecen debajo (o escribe `Other`).
- **Enable mature content:** márcalo si el directo es para +18.

### 6. Pulsa **Go Live**

La aplicación le pide a Streamlabs que prepare la sesión y te muestra:

- **Stream URL** → la URL del servidor RTMP.
- **Stream Key** → la clave de retransmisión (aparece oculta; se copia con el
  botón).

Usa los botones **Copy URL** y **Copy Key** para copiarlas. Por seguridad, la
clave **se borra del portapapeles a los 60 segundos**.

### 7. Pega los datos en OBS

Ver [Cómo emitir en OBS](#cómo-emitir-en-obs).

### 8. Al terminar, pulsa **End Live**

Esto cierra la sesión en Streamlabs. **Es importante hacerlo**: si dejas una
sesión abierta, TikTok puede rechazarte el siguiente directo.

> Si la aplicación o el equipo se cierran de golpe con un directo preparado, la
> próxima vez que abras la aplicación te avisará y te ofrecerá **cerrar esa
> sesión pendiente** (o descartar el aviso).

---

## Cómo emitir en OBS

1. Abre OBS Studio.
2. **Ajustes** (o *Configuración*) → **Emisión**.
3. En **Servicio**, elige **Personalizado…**.
4. **Servidor:** pega la **Stream URL** que te dio la aplicación.
5. **Clave de retransmisión:** pega la **Stream Key**.
6. Pulsa **Aplicar** y luego **Empezar transmisión**.

No cambies nada más. Si OBS no conecta, revisa que hayas copiado los dos valores
completos y que no haya espacios de más delante o detrás.

---

## Dónde se guarda tu token (seguridad)

- El token **nunca** se escribe en el archivo de configuración (`config.json`).
  Ese archivo solo guarda preferencias: título, categoría, contenido para
  adultos y los datos de la sesión preparada (identificador, título y hora, sin
  ningún secreto).
- El token vive en el **almacén de credenciales del sistema**. Si tu sistema no
  tiene uno disponible, la aplicación te avisa y el token **solo dura la sesión
  abierta**: al cerrar, tendrás que volver a cargarlo.
- La aplicación **no imprime el token** ni lo escribe en el registro de
  actividad (log).
- Las versiones antiguas guardaban el token en texto plano dentro de
  `config.json`. Si la aplicación encuentra uno de esos archivos, te pregunta
  qué hacer: **importarlo** al almacén seguro, **borrar** el archivo antiguo o
  dejarlo para luego. Si eliges no importarlo, ese token **no se carga**.

👉 **Nunca publiques tu token ni tu stream key** en un *issue*, en un chat o en
una captura de pantalla: con ellos se pueden abrir y cerrar directos en tu
cuenta. Lee [`SECURITY.md`](SECURITY.md) antes de pedir ayuda.

---

## Actualizaciones

La aplicación comprueba si hay una versión nueva al arrancar (en segundo plano,
sin molestarte si no hay nada nuevo) y te ofrece:

- **Descargar:** baja el paquete de tu sistema a tu carpeta de descargas,
  mostrando el progreso y con opción de cancelar. Antes de darlo por bueno
  **verifica el checksum publicado**; si no coincide, borra el archivo.
  **La aplicación nunca ejecuta ni instala nada**: eso lo decides tú.
- **Abrir la página del release:** para que elijas el archivo a mano.

---

## Problemas frecuentes

<details>
<summary><b>«Can Go Live: False» / el botón Go Live está bloqueado</b></summary>

Tu cuenta no tiene permiso de emisión vía Streamlabs. Solicítalo (no hacen falta
1.000 seguidores) y espera la aprobación. Mientras tanto no hay nada que la
aplicación pueda hacer: es un requisito de TikTok/Streamlabs.
</details>

<details>
<summary><b>«El token de Streamlabs ha caducado o no es válido»</b></summary>

Vuelve a cargarlo con **Load from Web** (o *Load from PC*) y pulsa **Refresh
Account Info**. Si tenías el token guardado, se reemplaza solo.
</details>

<details>
<summary><b>No encuentra el token con «Load from PC»</b></summary>

- Comprueba que Streamlabs Desktop está instalado **y con la sesión de TikTok
  iniciada**.
- En Linux esa opción no existe: usa **Load from Web**.
- Si tu antivirus bloquea la lectura, usa **Load from Web**.
</details>

<details>
<summary><b>Mi antivirus marca el programa</b></summary>

Es esperable: la opción «Load from PC» lee el almacén local de otra aplicación
(la misma técnica que usan los ladrones de credenciales), así que algunos
antivirus se quejan. Si no te fías, usa solo **Load from Web**, o compila el
programa tú mismo desde el código fuente.
</details>

<details>
<summary><b>macOS: «la aplicación está dañada o está incompleta»</b></summary>

Es la cuarentena de Gatekeeper sobre un binario sin firmar. Si el checksum
coincide, quita la cuarentena:

```bash
xattr -dr com.apple.quarantine /ruta/a/StreamLabsTikTokStreamKeyGenerator.app
```
</details>

<details>
<summary><b>OBS no conecta / TikTok rechaza el directo</b></summary>

1. Comprueba que **can Go Live** sea `True`.
2. Pulsa **End Live** en la aplicación y vuelve a pulsar **Go Live** para generar
   una sesión nueva (las claves caducan).
3. Verifica que has pegado la URL y la clave **completas** y sin espacios.
4. Si el problema empezó justo después de cerrar la aplicación de golpe, deja que
   te ofrezca **cerrar la sesión anterior** al abrirla.
</details>

<details>
<summary><b>¿Dónde están los registros para pedir ayuda?</b></summary>

Pulsa el botón **Logs** en la aplicación: se abre la carpeta con `app.log`. Ese
archivo **no contiene tokens, códigos de autorización ni stream keys**, así que
es lo que debes adjuntar si abres un *issue*. Aun así, échale un vistazo antes de
enviarlo.

Si necesitas más detalle, arranca la aplicación con registro en modo depuración:

```powershell
$env:STREAMLABS_KEYGEN_LOG_LEVEL = "DEBUG"; .\StreamLabsTikTokStreamKeyGenerator.exe
# o desde el código fuente:
$env:STREAMLABS_KEYGEN_LOG_LEVEL = "DEBUG"; python StreamLabsTikTokStreamKeyGenerator.py
```
</details>

<details>
<summary><b>¿Necesito 1.000 seguidores para el acceso de Streamlabs?</b></summary>

No. Puedes solicitarlo con menos seguidores.
</details>

---

## Ejecutar desde el código fuente

Requiere **Python 3.11 o superior** (el CI prueba con 3.12 y compila con 3.13).

```bash
git clone https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator.git
cd StreamLabsTikTokStreamKeyGenerator
python -m pip install -r requirements.txt
python StreamLabsTikTokStreamKeyGenerator.py
```

Para desarrollar y pasar las pruebas:

```bash
python -m pip install -r requirements-dev.txt
ruff check .
pytest
```

El código fuente **no necesita** el archivo `_version.py` (lo genera el proceso
de compilación); sin él usa una versión de desarrollo, y las versiones de
desarrollo nunca avisan de actualizaciones.

---

## Publicar una versión nueva (mantenedor)

Basta con empujar una etiqueta con formato `vMAYOR.MENOR.PARCHE`:

```bash
git tag v2.1.0
git push origin v2.1.0
```

Eso ejecuta las pruebas, compila **Windows, macOS (x86_64 y arm64) y Linux**,
genera `SHA256SUMS.txt` y publica la release con notas generadas
automáticamente.

**Enlaces útiles durante la publicación:**

| | |
|---|---|
| [Ver la compilación en marcha](https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/actions/workflows/release.yml) | Estado de cada sistema en tiempo real |
| [Lanzarla a mano](https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/actions/workflows/release.yml) → *Run workflow* | Para escribir tú el changelog |
| [Descargar artefactos de una compilación](https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/actions/workflows/release.yml) → abre un *run* → sección **Artifacts** | Sirve para probar una compilación antes de publicarla |
| [Versiones publicadas](https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/releases) | Borrar o editar una release |

Si una compilación falla, no hace falta crear otro tag: abre el *run* y usa
**Re-run failed jobs** (o **Re-run all jobs**).

---

## Avisos y limitaciones

- **Endpoints internos.** Las operaciones usan los endpoints que Streamlabs
  Desktop emplea por dentro (`/api/v5/slobs/tiktok`), no una API pública, y el
  inicio de sesión se hace con la identificación de Streamlabs Desktop. Si
  Streamlabs cambia su aplicación, esto puede dejar de funcionar y habrá que
  actualizar el programa.
- **Términos de servicio.** Usar estos endpoints puede quedar fuera de los
  términos de Streamlabs. **Las consecuencias recaen sobre la cuenta que
  autoriza el token**, no sobre el autor del programa. Valóralo antes de usarlo.
- **«Load from PC»** lee el almacén local de otra aplicación en tu equipo (ver
  arriba).
- **Binarios sin firmar.** Windows y macOS pueden avisar al ejecutarlos.
  Comprueba siempre el checksum y no desactives Gatekeeper a ciegas.
- **TikTok y Streamlabs pueden cambiar sus reglas de acceso** en cualquier
  momento; no todas las cuentas reciben clave RTMP.

---

## Atribución y licencia

La aplicación original la escribió [Loukious](https://github.com/Loukious) y se
distribuye bajo licencia **GPL-3.0**. Este repositorio es una obra derivada y
mantiene esa misma licencia; consulta [`LICENSE.txt`](LICENSE.txt).

Por continuidad, el directorio de configuración y el nombre del servicio en el
almacén de credenciales siguen usando el identificador del autor original:
cambiarlos dejaría huérfanas la configuración y el token guardado de las
instalaciones que ya existen.
