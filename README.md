# FPV Stream — Generador de clave de transmisión de TikTok para OBS Studio

## Description
This application is a simple tool that generates a TikTok Live Stream Key for OBS Studio using the Streamlabs API. Streamlabs TikTok LIVE access is required.

## Features
- Generate TikTok Live Stream Key using Streamlabs API

## Requirements
- Streamlabs TikTok LIVE access. You can request access [here](https://tiktok.com/falcon/live_g/live_access_pc_apply/result/index.html?id=GL6399433079641606942&lang=en-US)
- TikTok account
- Streamlabs installed on your computer and you are logged in with your TikTok account in Streamlabs (optional)

## Download
- Download the latest release from [here](../../releases/latest)

## Usage
1. Run the application.
2. Click on the "Cargar desde el PC" button if you have Streamlabs installed on your computer and you are logged in with your TikTok account in Streamlabs, otherwise click on the "Cargar desde la web" button.
3. Select stream title and category.
4. Click on "Guardar configuración" button to save the token, title and category.
5. Click on the "Preparar transmisión" button.

Solo puede haber una instancia abierta por archivo de configuración: si abres otra,
se enfoca la ventana existente para evitar dos escritores del token.

### Cambiar cuenta

Pulsa **Cambiar cuenta** para borrar del generador el token, el usuario y las claves
anteriores y abrir un nuevo acceso. En la página de TikTok, pulsa **Cambiar de cuenta**
y elige la cuenta que quieres usar. Si cancelas, la cuenta anterior no se restaura.
Si hay una transmisión preparada, finalízala o confirma su cierre en Live Monitor
antes de cambiar. Los datos se guardan en `config.json`, junto a la aplicación. Si
esa carpeta no es escribible (por ejemplo, Program Files o una app de macOS), se
usa la configuración del usuario: `%APPDATA%\FPV Stream`,
`~/Library/Application Support/FPV Stream` o `~/.config/fpv-stream`, migrando el
archivo anterior la primera vez.

Esta opción no cierra la sesión de TikTok en otras pestañas ni cambia la cuenta
guardada en Streamlabs Desktop.


## Screenshots

![Screenshot](https://i.imgur.com/2PSgEQP.png)

## Output

The app will output:
- **Stream URL:** The URL needed to connect to the TikTok live stream.
- **Stream key for OBS Studio (or any other streaming app):** Stream key that that you can use in OBS Studio to stream to TikTok.

## Checkout my OBS-Multi-RTMP plugin fork!
With [this](https://github.com/Loukious/obs-multi-rtmp) plugin, you can use your streamlabs token to stream directly to TikTok by saving it only once.

## FAQ
### I'm getting you `You can't open the application "***" because it may be damaged or incomplete` error on MacOS. What should I do?
I don't own a Mac so I can't test the app on MacOS but you can try the following:
1. Open Terminal.
2. Run the following command: `xattr -dr com.apple.quarantine /path/to/the/StreamLabsTikTokStreamKeyGenerator.app` (replace `/path/to/the/StreamLabsTikTokStreamKeyGenerator.app` with the path to the app).
3. Try to run the app again.

### I'm getting an error when I try to stream. What should I do?
1. First make sure it's not an issue related to Streamlabs. Try going live using Streamlabs and see if you get the same error.
2. If it's not an issue related to Streamlabs, you can create an issue on GitHub with the error message and a screenshot of the error.
### Do I need to have 1k followers to get Streamlabs TikTok LIVE access?
No, you can request access even if you have less than 1k followers.
