# TRS4 Sims

Estructura reorganizada del proyecto:

- `probando.py`: lanzador principal.
- `src/trs4_sims/`: codigo activo de la aplicacion.
- `data/`: configuraciones JSON y archivos `.txt` de trabajo.
- `vendor/tsr_downloader/`: downloader externo usado por la app.
- `legacy/`: scripts viejos o experimentales conservados por referencia.
- `downloads/`: carpeta destino por defecto para descargas.

El punto de entrada sigue siendo:

```powershell
python probando.py
```
