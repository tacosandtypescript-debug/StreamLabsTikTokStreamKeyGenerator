# Dónde se quedó el trabajo

Última sesión: 21 de septiembre. Este archivo existe para retomar sin volver a
deducir lo ya deducido. Se puede borrar cuando el LIVE quede confirmado.

## Lo que está hecho y funcionando

- **Máquina de estados del directo** (`live_state.py`): Sin sesión → Preparando →
  Preparado → Esperando OBS → Iniciando → EN VIVO → Finalizando → Finalizado.
  Cada ciclo es nuevo; nada del directo anterior sobrevive.
- **Detección de OBS** (`live_ingest.py`): lee la tabla de conexiones TCP del
  sistema y ve si OBS está enviando al RTMP. Windows con `ctypes`, Linux con
  `/proc/net/tcp`. **Medido: detecta la conexión en 64 ms.**
- **Vigilancia por hilo aparte** (`live_watch.py`, `ui/live_thread.py`): no
  congela la ventana. Intervalos de 2 s mientras espera, 30 s ya en vivo.
- **Presupuesto de latencia** (`live_timeline.py`): cada etapa con su marca de
  tiempo relativa.
- **La app no es el cuello de botella**: 30 ms desde la petición hasta tener las
  credenciales en pantalla.

## Lo único que falta

**Confirmar el LIVE con TikTok.** `GET /stream/{broadcast_id}` devuelve **HTTP 405**
= la ruta existe, el método está mal. Sin esto, tras empezar a emitir la app se
queda en «Iniciando transmisión…» y no pasa a EN VIVO.

### Cómo resolverlo, en orden

1. En la app: **Cuenta y token → «Guardar el token de forma segura»**. Guarda el
   token cifrado en el almacén de Windows, que es lo que permite sondear desde
   fuera sin tocar la sesión abierta.
2. Ejecutar, con un directo preparado:
   ```bash
   python tools/probe_live_status.py <broadcast_id>
   ```
   Prueba varios métodos y rutas y dice cuál responde. **Solo lecturas.**
3. Con el método bueno, cambiar `live_status()` en `streamlabs_client.py` — ya está
   escrito defensivo: lee la respuesta sin asumir un contrato exacto y devuelve
   `live=None` (desconocido) cuando no la entiende. **Nunca** lo convierte en «no
   está en vivo».
4. Verificar con un directo real: Preparar → OBS → EN VIVO → Finalizar, y **dos
   seguidos sin reiniciar**, que es lo que pidió el usuario.

## Lo que se descartó, para no repetirlo

- **`liveRoomStatus`**: vale 0 tanto en vivo como apagado. No sirve.
- **Bloques de reproducción** (`streamData.pull_data`, URLs `.flv`/`.m3u8`): aparecen
  **también en salas ya terminadas**. `@tiktok`, que no emite, devuelve los mismos 6
  bloques que una cuenta en directo. **No sirven como señal**.
- **Socket de ingesta en puerto 1935**: la URL real es
  `rtmps://push-rtmp-f5-sg01.tiktokcdn.com:443/game`. **Puerto 443, no 1935.** El
  código lo lee de la URL, así que está bien, pero conviene recordarlo.

## Vía prometedora, SIN CONFIRMAR — empezar por aquí

`LiveRoom.liveRoomUserInfo.liveRoom.user.status` parece distinguir en vivo de
terminado. Observado en la misma cuenta, el mismo día:

| Momento | `user.status` |
|---|---|
| Emitiendo en directo | **2** |
| Minutos después, directo terminado | **4** |

`@tiktok` (no emite) también daba 4.

**Ojo: es una sola observación de cada estado.** Antes de construir nada encima hay
que confirmarlo varias veces y, sobre todo, **ver el cambio con la app abierta**:
si el valor pasa de 4 a 2 justo cuando OBS empieza a enviar, es la señal que falta.
Si resulta que 2 significa otra cosa (por ejemplo «tiene sala creada»), quedaría
descartada como las demás.

Se comprueba con:

```bash
python tools/probe_public_live.py
```

Es la única vía que **no necesita token**, así que merece la pena agotarla antes de
pedirle nada al usuario.


## Cómo reproducir el entorno

```bash
cd C:\Users\KTZ\Documents\StreamLabsTikTok\repo
.\.venv\Scripts\python.exe -m pytest -q          # 494 pruebas
.\.venv\Scripts\python.exe -m ruff check .
```

Para ver los diagnósticos en vivo:

```powershell
$env:STREAMLABS_KEYGEN_LOG_LEVEL = "DEBUG"
.\.venv\Scripts\python.exe StreamLabsTikTokStreamKeyGenerator.py
```

El registro está en
`%LOCALAPPDATA%\Loukious\StreamLabsTikTokStreamKeyGenerator\Logs\app.log`.

### Dos trampas del entorno, ya sufridas

- La app tarda ~3 s en arrancar y lanza la comprobación de actualización y el
  aviso de donación. Una instancia se cerró sola una vez sin dejar error en el
  registro.
- La aplicación **no roba el foco** en Windows: si se lanza desde un script, hay
  que hacer clic en ella. Eso no significa que no haya arrancado.

## Aviso sobre `service.json` de OBS

El perfil de OBS estaba apuntando a **Telegram** (`rtmps://dc1-1.rtmp.t.me/s/`), y
por eso la app decía «Esperando señal de OBS» con razón: no llegaba nada a TikTok.
Ya se corrigió a la URL de TikTok. Si vuelve a pasar, es lo primero que hay que
mirar:

```
%APPDATA%\obs-studio\basic\profiles\<perfil>\service.json
```

El usuario tiene el plugin **`aitum-multistream`**, que permitiría emitir a TikTok
y Telegram a la vez si algún día lo quiere.
