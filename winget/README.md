# Publicación en winget

[winget](https://learn.microsoft.com/es-es/windows/package-manager/) es el gestor de
paquetes de Windows: permite instalar la aplicación con
`winget install tacosandtypescript-debug.StreamLabsTikTokStreamKeyGenerator`, sin
PowerShell y sin sustos. El catálogo es el repositorio comunitario
[microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs), que **solo guarda
manifiestos YAML**, nunca los instaladores.

## Los manifiestos se generan solos

Cada release publica un asset `winget-manifests.zip` con los tres ficheros YAML ya
rellenos: la URL del instalador de esa versión y su `SHA256` **real**, calculado del
`.exe` que acaba de compilar el workflow. No hay que copiar ningún hash a mano.

Para generarlos o revisarlos en local:

```bash
python tools/make_winget_manifest.py \
  --installer Output/Setup-StreamLabsTikTokStreamKeyGenerator-2.2.0.exe \
  --version 2.2.0 \
  --output winget-out
```

## Cómo enviarlos (paquete nuevo)

1. **Firma el CLA.** Sin firmar el
   [Microsoft CLA](https://cla.opensource.microsoft.com) el PR se queda con la
   etiqueta `Needs-CLA` y no se puede fusionar. Solo hace falta la primera vez.
2. **Haz un fork** de `microsoft/winget-pkgs`. El repositorio es enorme, así que usa
   un clon parcial:

   ```bash
   git clone --filter=blob:none --no-checkout https://github.com/TU_USUARIO/winget-pkgs.git
   cd winget-pkgs
   git sparse-checkout set manifests/t/tacosandtypescript-debug
   git checkout
   ```

3. **Copia la carpeta** tal cual viene dentro de `winget-manifests.zip` (ya trae la
   ruta `manifests/t/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/<versión>/`).
   La ruta y el identificador distinguen mayúsculas de minúsculas: si no coinciden
   exactamente, la validación falla.
4. **Abre el PR** con el título exacto que pide la plantilla:
   `New package: tacosandtypescript-debug.StreamLabsTikTokStreamKeyGenerator version 2.2.0`.
   Un PR = un paquete = una versión, y solo ficheros de manifiesto.
5. **Espera la validación**: son diez pasos automáticos y luego la revisión de un
   moderador. La publicación suele tardar alrededor de una hora.

## Las dos comprobaciones que deciden si entra

- **Marca de terceros (política 2.2).** El identificador contiene «StreamLabs», que
  es marca de otra empresa. La política prohíbe *«misuse trademarks or impersonate
  other software»*, así que un moderador puede pedir un cambio. Si ocurre, la
  alternativa es publicar el paquete como
  `tacosandtypescript-debug.TikTokStreamKeyGenerator` y dejar claro en la
  descripción que es un cliente **no oficial**: lo único que se pierde es que
  `winget list` correlacione el paquete con el nombre que aparece en «Aplicaciones
  instaladas».
- **Escaneo de instaladores (paso 07).** El `.exe` se analiza con varios antivirus
  y contra los criterios de PUA, y *«a package that is flagged as PUA cannot be
  accepted, regardless of the application's legitimacy»*. Esta aplicación lee la
  base de datos local de Streamlabs Desktop, que es justo el patrón que marcan
  algunos heurísticos: es el riesgo real de este paquete, no el formato.

## Actualizar una versión publicada

Cuando el paquete ya está aceptado, cada versión nueva es un PR más pequeño:

```bash
wingetcreate update tacosandtypescript-debug.StreamLabsTikTokStreamKeyGenerator \
  --version 2.3.0 \
  --urls https://github.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/releases/download/v2.3.0/Setup-StreamLabsTikTokStreamKeyGenerator-2.3.0.exe \
  --submit
```

O copiar a mano la carpeta nueva que publica la release. El `AppId` del instalador
es fijo, así que winget actualiza en el sitio en vez de apilar una segunda copia.

## Por qué un instalador y no el ZIP

`winget` **no puede** empaquetar un ZIP portable de un build de Nuitka: los enlaces
que crea en `%LOCALAPPDATA%\Microsoft\WinGet\Links` fuerzan la extensión `.exe` y no
se pueden enlazar las DLL que van al lado, así que la aplicación no arrancaría; y en
moderación la etiqueta `Portable-Archive` bloquea el PR. Por eso la release publica
un instalador de Inno Setup (`InstallerType: inno`) además del ZIP.
