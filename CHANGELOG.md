# Registro de cambios

## Sin publicar

### Corregido

- **La ventana se redimensionaba sola unos segundos después de moverla.** Qt manda
  `showEvent` otra vez cada vez que una ventana se muestra tras estar oculta
  —restaurada de la barra de tareas, des-minimizada— y el ajuste inicial corría en
  todas ellas, devolviendo la ventana al tamaño de su contenido. Medido: se pedía
  `700x620` y a los cinco segundos volvía a `700x969` por su cuenta.
- **La ventana vuelve a ajustarse a su contenido**, que es lo que debe hacer: al
  validar la cuenta aparece la tarjeta del perfil, y al abrir la lista de categorías
  crece. Antes solo se medía una vez, así que lo que llegaba después se recortaba.

### Añadido

- **Guía de primeros pasos dentro de la aplicación.** Al abrirla por primera vez
  aparecía una pantalla llena de campos —token, permiso, categoría, OBS— sin nada
  que dijera cuál importaba primero ni en qué punto estabas. Ahora hay una tarjeta
  con los cinco pasos en orden, marcando el que toca, y se aparta sola cuando el
  directo está preparado. Cada paso se comprueba contra el mismo estado que habilita
  los botones, así que **la guía no puede marcar como hecho algo que no lo está**;
  una guía que miente es peor que no tener guía. Se oculta con «Ocultar» y se
  recupera desde «Más» → «Ver la guía de primeros pasos».
- **El motivo que da Streamlabs al denegar el permiso de emisión.** La respuesta de
  `/info` trae un campo `reason` que se estaba descartando, así que el usuario veía
  «Puede emitir: No» sin saber si tenía que solicitar el acceso, esperar o revisar
  algo. Un rechazo sin motivo es lo menos útil que puede decir una pantalla.

- **Presupuesto de latencia del arranque.** Cada directo anota, con la décima de
  segundo, cuándo ocurrió cada etapa desde que las credenciales estuvieron listas:
  `SESSION_CREATED`, `RTMP_READY`, `WAITING_FOR_INGEST`, `OBS_CONNECTED`,
  `TIKTOK_RECEIVING_STREAM`, `LIVE_CONFIRMED`, `LIVE_ENDED`. `OBS_CONNECTED` se mide
  con un hilo propio que muestrea la tabla de conexiones cada 0,1 s, porque el
  vigilante de estados es demasiado lento para fechar ese instante. Responde a la
  pregunta «¿por qué tarda en arrancar?» con números en vez de con opiniones.
- `tools/probe_live_status.py` y `tools/probe_public_live.py`: sondean, solo con
  lecturas, qué endpoint y qué método informan del estado real del directo.

### Medido

- **La aplicación no es el cuello de botella.** En una prueba real: credenciales
  listas en `t+0.00s` y `RTMP_READY` en `t+0.03s`. **30 ms.** El resto del tiempo es
  OBS y TikTok.
- **Detección de OBS: 64 ms.** OBS conectó al RTMP a las `04:47:16.472` y la
  aplicación lo detectó a las `04:47:16.536`. El salto de «Esperando señal de OBS» a
  «Iniciando transmisión…» funcionó solo, sin tocar nada.

### Pendiente, y es lo que queda por resolver

- **Confirmar el LIVE con TikTok.** `GET /stream/{broadcast_id}` responde **HTTP
  405**, que significa que la ruta existe y el método está mal — no que la ruta no
  exista. Hasta dar con el método correcto, la aplicación detecta la señal de OBS
  pero se queda en «Iniciando transmisión…» y **no** pasa a EN VIVO.
- Se descartó la página pública de TikTok como fuente: devuelve datos de
  reproducción también para salas **ya terminadas** (`@tiktok`, que no emite,
  devuelve los mismos 6 bloques que una cuenta en directo). Construir sobre eso
  habría hecho decir «EN VIVO» con el directo apagado.

### Corregido

- **Un cierre rechazado se contaba como si se hubiera perdido la conexión.** Cuando
  Streamlabs responde `2xx` pero el cuerpo trae `success: false`, el error salía sin
  código HTTP y el diálogo decía «vuelve a pulsarlo». Ese es el consejo equivocado:
  la petición llegó y fue entendida, así que reintentarla falla igual, y lo más
  probable es que no quedara nada que cerrar. Ahora ese caso se distingue, lleva su
  código HTTP y explica que conviene descartar la sesión si vuelve a rechazarse.
  Importa porque una sesión que se conserva **bloquea «Preparar directo»**: sin esta
  salida, el usuario se queda en un bucle sin saber por qué.
- El registro de ese fallo dejó de apoyarse en el valor de `success`: se anota su
  *tipo*, nunca su contenido.

## v2.8.0

Rediseño de la interfaz entera. Nada de lo que hace la aplicación cambia: cambia
cómo se ve y cómo se coloca.

### Añadido

- **Franja de resumen** en la pantalla principal: *Cuenta · Puede emitir · Sesión*.
  Contesta de un vistazo las tres preguntas que antes obligaban a entrar en
  «Cuenta y token» para comprobarlas, y se alimenta del mismo estado que decide si
  los botones están activos, así que no puede contradecirlos.
- **Cifras del perfil en columnas**, con el número grande y el rótulo debajo
  (Seguidores, Me gusta), como las dibuja el propio perfil.
- **Halo desplazado cian y rosa** en la foto de la cuenta, el borde de color que
  lleva el avatar en la red.
- **Iconos dibujados** para todos los botones: preparar, finalizar, guardar,
  comprobar, leer del equipo, iniciar sesión, enlace, clave y escudo. Los dibuja la
  aplicación, así que no dependen de ninguna fuente instalada — que es justo el
  fallo que este repositorio ya documenta con los emoji.
- `tools/capture_ui.py`: guarda la ventana real a PNG, en los dos temas y las dos
  pantallas, para poder revisar la interfaz sin abrirla a mano.
- `docs/interfaz.html`: la comparativa antes y después, con las capturas.

### Cambiado

- **Formato móvil, en una sola columna.** La ventana pasa de 480 × 712 fijos a
  430 × 909, estrecha y alta, con todo apilado en vertical: banner, perfil,
  tarjetas, botones y resumen. Es la forma que se coloca bien al lado de OBS.
- **La ventana se redimensiona.** Antes no se podía: era exactamente del tamaño de
  su contenido y el botón de maximizar estaba quitado. Ahora se abre del tamaño que
  pide su contenido, su mínimo es 430 × 360, y el tamaño que elijas no se te quita
  — las mediciones posteriores solo mueven el mínimo.
- **La paleta pasa a la de TikTok**: cian `#25f4ee` y rosa `#fe2c55` sobre el negro
  `#010101`. El cian llena el botón principal y el anillo de la foto; el rosa queda
  para *Finalizar directo*, la única acción que tira trabajo a la basura. Como el
  blanco sobre ese cian no se lee, los botones llevan texto negro y los enlaces un
  cian oscurecido.
- **Los cuadros**: cada tarjeta es una sección con su título en pequeño y una línea
  fina debajo, no una caja con una palabra suelta arriba. En tema oscuro las
  tarjetas son apenas un punto más claras que el fondo y el borde es un susurro; los
  campos quedan un escalón por encima, porque un campo que no se ve no se encuentra.
- **El foco ya no engorda el borde** —eso hacía saltar el campo un píxel al entrar el
  cursor— sino que cambia de color.
- **Botones y textos**: *Guardar datos* → *Guardar ajustes*, *Actualizar datos de la
  cuenta* → *Comprobar la cuenta*, *Cargar desde el PC* → *Leer del equipo*. Como a
  430 px tres botones no caben en una fila, *Preparar directo* ocupa el ancho
  completo y debajo van *Finalizar directo* y *Guardar ajustes*.
- `--check` comprueba que la ventana **se pueda redimensionar**, en vez de exigir que
  fuera de tamaño fijo.

### Corregido

- **La ventana se abría más corta de lo que necesitaba**, con barra de
  desplazamiento sobre contenido que cabía de sobra. La marca de «tamaño ya
  decidido» se ponía antes de que Qt hubiera aplicado las fuentes y envuelto los
  textos, así que la medición buena no llegaba a usarse nunca; en un caso real eran
  121 px de más. Ahora se mide cuando la ventana ya está en pantalla.
- **`ok` y `live` compartían color**, así que «correcto» y «directo preparado» se
  pintaban igual en el banner y en el resumen. Tienen colores distintos.
- El rótulo de las cifras del perfil dibujaba el número en lugar del rótulo.

### Notas

- Los 441 tests pasan y `ruff` no da avisos. Ocho pruebas fijaban el comportamiento
  de ventana fija y se han actualizado a la garantía nueva.
- Sigue haciendo falta llamar a **Finalizar directo** antes de cerrar, y las claves
  siguen caducando: nada de eso ha cambiado.
