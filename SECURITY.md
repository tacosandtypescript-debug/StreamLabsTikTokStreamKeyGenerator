# Política de seguridad

## Qué maneja esta aplicación

Guarda y usa un **token OAuth de Streamlabs** que puede **iniciar y cerrar
directos en tu cuenta de TikTok**, y además puede leer el token que el cliente
Streamlabs Desktop tiene guardado en tu equipo. Trata ese token como una
contraseña.

El token vive en el almacén de credenciales del sistema operativo (Administrador
de credenciales de Windows, Llavero de macOS, Secret Service en Linux). **Nunca**
se escribe en `config.json`, y la aplicación no lo imprime ni lo escribe en el
registro de actividad.

## No publiques esto nunca en un issue, un chat o una captura

- Tu token de Streamlabs (`oauth_token`, `apiToken`): con él se pueden abrir y
  cerrar directos en tu cuenta.
- Tu clave de retransmisión de TikTok o la URL RTMP.
- Una captura con el campo del token mostrado con el botón del ojo.
- Tu `config.json` — no contiene el token, pero revísalo antes de compartirlo.

**Si ya has publicado un token, revócalo primero** (cerrando la sesión en
Streamlabs Desktop se invalida el token guardado) y solo después edita o borra el
mensaje. Rotar la credencial importa mucho más que esconder el mensaje.

## Qué incluir al pedir ayuda

- La versión de la aplicación (aparece en el aviso de actualización, o en
  `version.py`).
- Tu sistema operativo.
- El registro: pulsa **Registros** en la aplicación y adjunta el `app.log` que
  abre. Por diseño no contiene tokens, códigos de autorización ni claves de
  retransmisión, pero échale un vistazo antes de enviarlo.

## Cómo reportar una vulnerabilidad

Usa la pestaña **Security → Report a vulnerability** de GitHub para cualquier
cosa sensible, o abre un *issue* normal si el problema no es delicado. Un ejemplo
con los datos tachados es siempre suficiente: no envíes nunca un token ni una
clave que funcione.
