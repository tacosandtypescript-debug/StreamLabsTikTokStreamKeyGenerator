# Generador de clave de TikTok Live para OBS (vía Streamlabs)

[![Pruebas](https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/actions/workflows/test.yml/badge.svg)](https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/actions/workflows/test.yml)
[![Compilación y publicación](https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/actions/workflows/release.yml/badge.svg)](https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/actions/workflows/release.yml)
[![Última versión](https://img.shields.io/github/v/release/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator?label=descarga)](https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/releases/latest)
[![Licencia](https://img.shields.io/badge/licencia-GPL--3.0-blue)](LICENSE.txt)

Aplicación para **Windows, macOS y Linux** que te da la **URL y la clave de
retransmisión de TikTok Live** para pegarlas en OBS Studio. La sesión se prepara
a través de Streamlabs.

> No emite vídeo ni configura OBS: eso pasa cuando OBS se conecta con esos datos.

| Ventana principal, tema claro | Ventana principal, tema oscuro |
|---|---|
| ![Interfaz en tema claro](docs/captura-clara.png) | ![Interfaz en tema oscuro](docs/captura-oscura.png) |

La pantalla de cuenta, donde se carga el token, se comprueba el permiso y se elige la
foto (en la imagen, con una puesta):

![Pantalla de cuenta y token](docs/captura-cuenta.png)

---

## 📥 Instalación

### Windows — PowerShell

```powershell
irm https://raw.githubusercontent.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/main/install.ps1 | iex
```

### macOS y Linux — Terminal

```bash
curl -fsSL https://raw.githubusercontent.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/main/install.sh | bash
```

Los dos comandos descargan la última versión, **verifican su checksum** y la
instalan en tu carpeta de usuario con acceso directo. **No piden permisos de
administrador.**

Como estos comandos ejecutan un script, conviene saber qué ejecutan: son cortos y
legibles — [`install.ps1`](install.ps1) e [`install.sh`](install.sh).

### Windows — instalador

La release también publica un **`Setup-*.exe`**. Es una instalación por usuario
(sin administrador) que aparece en *Aplicaciones instaladas*, crea los accesos
directos y se desinstala desde ahí.

Si ya tienes la aplicación instalada, **puede actualizarse sola**: al detectar una
versión nueva te ofrece *Instalar ahora*, descarga el instalador, comprueba su
checksum, se cierra y vuelve a abrirse ya actualizada. Nunca lo hace mientras hay
un directo preparado, y siempre puedes elegir *Descargar* para hacerlo tú.

### O descarga manual

| | |
|---|---|
| **[⬇️ Última versión](https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/releases/latest)** | El ZIP de tu sistema, el `Setup-*.exe` de Windows + `SHA256SUMS.txt` |
| [Todas las versiones](https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/releases) | Historial |
| [Compilación automática](https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/actions/workflows/release.yml) | Estado de cada sistema |
| [Estado de las pruebas](https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/actions/workflows/test.yml) | Ubuntu, Windows y macOS |

Elige el archivo según tu sistema: **`-win-`** (Windows), **`-arm64-macos-`**
(macOS Apple Silicon), **`-x86_64-macos-`** (macOS Intel), **`-linux-`** (Linux).

Comprueba el checksum antes de ejecutarlo:

```powershell
# Windows
Get-FileHash .\StreamLabsTikTokStreamKeyGenerator-win-<versión>.zip -Algorithm SHA256
```
```bash
# macOS / Linux
shasum -a 256 StreamLabsTikTokStreamKeyGenerator-<sistema>-<versión>.zip
```

Compara el valor con su línea de `SHA256SUMS.txt`. Si no coincide, **no lo
ejecutes**: vuélvelo a descargar.

---

## 🚀 Uso en 5 pasos

1. Abre la aplicación.
2. **Iniciar sesión web** (recomendado) o **Cargar desde el PC** si usas
   Streamlabs Desktop. También puedes pegar un token a mano.
3. **Actualizar datos de la cuenta** → debe aparecer *Puede emitir: True*.
4. Opcional: **Guardar token de forma segura** para no repetir el login.
5. Escribe el **título** y la **categoría** → **Preparar directo** → **Copiar URL**
   y **Copiar clave**.

La ventana es **pequeña y de tamaño fijo**: mide exactamente lo que mide su
contenido, no se redimensiona y no tiene zonas vacías. Te dice en todo momento en
qué punto estás: el **banner de arriba** cambia de color y de texto («Sin token»,
«Cuenta sin validar», «Listo para preparar el directo», «Directo preparado»), y la
**barra de abajo** muestra qué está pasando mientras se consulta la cuenta o se
prepara la sesión.

El token y el permiso de emisión están en una **segunda pantalla**, para que la
principal tenga solo lo que se usa antes de cada directo: se entra con el botón
**Cuenta y token** y se vuelve con **Volver al directo**. La primera vez que abres
la aplicación, esa pantalla es la que aparece.

### La cuenta y su foto

El **círculo con tu inicial** que ves en el banner y en la ficha de cuenta se colorea
solo, de forma estable, a partir del nombre: dos cuentas nunca se confunden.

**No se descarga ninguna foto**, y no es por falta de ganas: Streamlabs no publica el
avatar de la cuenta autorizada (el endpoint solo devuelve el nombre, el estado y las
opciones de audiencia) y TikTok solo sirve el suyo a un navegador de verdad —a un
cliente normal le devuelve una página vacía o un 403—. Si quieres una foto, en
**Cuenta y token → Elegir imagen…** puedes escoger una tuya: se guarda una copia
reducida a 256 px en la carpeta de configuración, se puede quitar con **Quitar** y no
sale de tu equipo.

La casilla **Contenido para adultos** depende de lo que Streamlabs responda para tu
cuenta: si tu cuenta no puede usarlo, aparece deshabilitada y explicada.

### Atajos de teclado

| Atajo | Qué hace |
|---|---|
| `Ctrl+Intro` | Preparar directo |
| `Ctrl+Mayús+Intro` | Finalizar directo |
| `Ctrl+D` | Guardar el informe de diagnóstico |
| `Ctrl+L` | Abrir la carpeta de registros |
| `F1` | Ayuda |

### En OBS

Ajustes → **Emisión** → Servicio: **Personalizado** → pega la **URL del servidor**
y la **Clave de retransmisión** → Aplicar.

Al terminar, detén primero la salida de TikTok en OBS y después pulsa
**Finalizar directo** para cerrar la sesión en Streamlabs (si la dejas abierta,
TikTok puede rechazar el siguiente directo).

> Si la aplicación se cierra de golpe con un directo preparado, al volver a
> abrirla te ofrecerá **cerrar esa sesión pendiente**.

---

## 🔒 Tu token

- Se guarda **cifrado en el almacén de credenciales del sistema** (Windows,
  macOS, Linux). **Nunca** en `config.json`.
- La aplicación **no lo imprime** ni lo escribe en los registros.
- **No lo publiques** en un issue ni en una captura. Lee [`SECURITY.md`](SECURITY.md).

---

## 🧰 Si algo falla

| Problema | Qué hacer |
|---|---|
| *Puede emitir: False* | Tu cuenta no tiene acceso LIVE vía Streamlabs: [solicítalo](https://tiktok.com/falcon/live_g/live_access_pc_apply/result/index.html?id=GL6399433079641606942&lang=en-US) (no hacen falta 1000 seguidores). |
| **Preparar directo** deshabilitado | Valida la cuenta y elige una categoría de la lista. |
| «El token ha caducado» | Vuelve a **Iniciar sesión web**. |
| OBS no conecta | **Finalizar directo** y **Preparar directo** otra vez (las claves caducan). |
| **Finalizar directo** muestra un error | La app reintenta los fallos temporales y conserva la sesión para volver a pulsarlo. Si la sesión ya había terminado, un `404` se considera cierre correcto. |
| «No hay almacén seguro» en Linux | Instala `libsecret` (`sudo apt install libsecret-1-0`). |
| Antivirus avisa | Es por **Cargar desde el PC**, que lee el almacén de Streamlabs Desktop (la misma técnica que usan los ladrones de credenciales). Usa **Iniciar sesión web**. |
| macOS dice que está dañado | `xattr -dr com.apple.quarantine /ruta/StreamLabsTikTokStreamKeyGenerator.app` |
| Necesitas ayuda | **Más → Guardar informe de diagnóstico** y adjunta el ZIP: lleva tus datos de entorno y el registro, sin tokens ni claves. |

El informe incluye la versión, el sistema, dónde está instalada la aplicación y las
últimas líneas del registro, todo pasado por un filtro que borra el token y la clave
de retransmisión. Es lo que hay que adjuntar en una incidencia.

El registro identifica cada operación, endpoint, código HTTP, duración y campos
ausentes cuando una respuesta cambia. No guarda títulos, tokens, claves,
respuestas completas ni identificadores de sesión.

---

## 💻 Desde el código fuente

Python **3.11 o superior**. Todas las dependencias en un comando:

```bash
python -m pip install -r https://raw.githubusercontent.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/main/requirements.txt
```

O el flujo completo:

```bash
git clone https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator.git
cd StreamLabsTikTokStreamKeyGenerator
python -m pip install -r requirements.txt
python StreamLabsTikTokStreamKeyGenerator.py
```

Para desarrollar: `python -m pip install -r requirements-dev.txt`, `ruff check .`
y `pytest` (261 pruebas, también de la interfaz). Los iconos se regeneran con
`node tools/make_icons.mjs` y los manifiestos de winget con
`python tools/make_winget_manifest.py`.

> En Windows, si `python` abre la Microsoft Store es que solo tienes el alias:
> instala Python desde [python.org](https://www.python.org/downloads/windows/)
> marcando *Add python.exe to PATH*.

---

## ⚠️ Avisos

- Usa los **endpoints internos de Streamlabs Desktop**, no una API pública: si
  Streamlabs cambia su aplicación, puede dejar de funcionar. El riesgo de los
  términos de servicio recae sobre **la cuenta que autoriza**.
- Los binarios **no están firmados**: Windows SmartScreen o macOS Gatekeeper
  pueden avisar. Comprueba siempre el checksum.

---

## 📄 Licencia

GPL-3.0 — consulta [`LICENSE.txt`](LICENSE.txt). Obra original de
[Loukious](https://github.com/Loukious/StreamLabsTikTokStreamKeyGenerator); este
repositorio es una versión derivada, endurecida y traducida.
