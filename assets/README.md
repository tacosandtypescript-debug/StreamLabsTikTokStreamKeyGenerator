# Iconos de la aplicación

Arte original generado por `tools/make_icons.mjs` (sin dependencias externas) y
publicado bajo la misma licencia **GPL-3.0** que el resto del proyecto.

| Archivo | Formato | Uso |
| --- | --- | --- |
| `icon.png` | PNG 512×512 RGBA | Icono principal en Linux y en la ventana de la app. |
| `icon@2x.png` | PNG 1024×1024 RGBA | Versión de alta densidad (pantallas HiDPI/Retina). |
| `icon.ico` | ICO multi-tamaño | Windows: 16, 24, 32, 48, 64, 128 y 256 px (PNG incrustado). |
| `icon.icns` | ICNS | macOS: `ic07`–`ic14`, de 32 a 1024 px (PNG incrustado). |

## Cómo regenerarlos

```sh
node tools/make_icons.mjs
```

El script dibuja el icono en memoria con supersampling 4×4 y escribe los cuatro
archivos de `assets/` de forma determinista (mismos bytes en cada ejecución).
Solo necesita Node.js: el codificador PNG, el empaquetador ICO y el de ICNS
están implementados en el propio script.

Si cambias el diseño (colores o geometría del objeto `DESIGN`), vuelve a
ejecutar el comando y actualiza los binarios en el mismo cambio.
