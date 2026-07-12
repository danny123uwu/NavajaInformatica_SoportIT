"""
Navaja Suiza - Suite de Soporte Técnico
Interfaz de terminal (TUI) para generar y explorar resúmenes de logs del sistema.

Se usa Textual en vez de Flet porque:
- Es texto/terminal puro: corre igual en local o por SSH (ideal para soporte de redes).
- Su API es mucho más estable entre versiones (Flet cambiaba cosas cada rato).
- Se empaqueta muy fácil como ejecutable portable con PyInstaller.
"""

import os
import datetime
import subprocess

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Header, Footer, Input, Button, DataTable, Label, Static, DirectoryTree

import log_engine


class DirectoryPickerScreen(ModalScreen):
    """Ventana modal para elegir una carpeta navegando el árbol de directorios.

    Teclas dentro del árbol:
      - Flechas arriba/abajo: moverse entre carpetas y archivos.
      - Flecha derecha o Enter: abrir/expandir una carpeta.
      - Flecha izquierda: cerrar la carpeta expandida.
      - Backspace (o botón "Subir nivel"): subir un nivel en la ruta.
      - Escribir una ruta completa arriba y Enter: saltar directo ahí.
      - Esc: cancelar sin elegir nada.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancelar"),
        ("backspace", "go_up", "Subir un nivel"),
    ]

    def __init__(self, start_path: str):
        super().__init__()
        # Antes solo se podía navegar DENTRO de la carpeta de inicio (sin poder subir).
        # Ahora arrancamos en el Home del usuario, que es un punto de partida mucho
        # más útil (desde ahí ya se ve Escritorio, Documentos, Descargas, etc.),
        # y además se puede subir de nivel, ir a la raíz "/", o escribir cualquier ruta.
        home = os.path.expanduser("~")
        self.start_path = start_path if os.path.isdir(start_path) else home

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-box"):
            yield Label(
                "↑↓ moverse · →/Enter abrir carpeta · ← cerrar carpeta · "
                "Backspace subir un nivel · Esc cancelar",
                id="picker-help",
            )
            yield Static(f"📂 {self.start_path}", id="current-path-label")
            yield Input(
                placeholder="Escribe una ruta completa y presiona Enter (ej: /home/usuario/Descargas)",
                id="path-input",
            )
            with Horizontal(id="picker-shortcuts"):
                yield Button("🏠 Home", id="btn_home")
                yield Button("💻 Raíz /", id="btn_root")
                yield Button("⬆ Subir nivel", id="btn_up")
                yield Button("✅ Usar esta carpeta", id="btn_use", variant="primary")
            yield DirectoryTree(self.start_path, id="dir-tree")

    def on_mount(self) -> None:
        self.query_one("#dir-tree", DirectoryTree).focus()

    def _go_to(self, path: str) -> None:
        path = os.path.abspath(os.path.expanduser(path))
        if os.path.isdir(path):
            tree = self.query_one("#dir-tree", DirectoryTree)
            tree.path = path
            self.query_one("#current-path-label", Static).update(f"📂 {path}")
        else:
            self.notify(f"Ruta no válida: {path}", severity="error")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "path-input":
            self._go_to(event.value.strip())

    def on_tree_node_highlighted(self, event) -> None:
        # Muestra en vivo, mientras te mueves con las flechas, dónde estás parado.
        if event.node is not None and event.node.data is not None:
            self.query_one("#current-path-label", Static).update(f"📂 {event.node.data.path}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn_home":
            self._go_to(os.path.expanduser("~"))
        elif bid == "btn_root":
            self._go_to("/")
        elif bid == "btn_up":
            self.action_go_up()
        elif bid == "btn_use":
            tree = self.query_one("#dir-tree", DirectoryTree)
            node = tree.cursor_node
            if node is not None and node.data is not None and os.path.isdir(str(node.data.path)):
                self.dismiss(str(node.data.path))
            else:
                self.dismiss(str(tree.path))

    def action_go_up(self) -> None:
        tree = self.query_one("#dir-tree", DirectoryTree)
        current = str(tree.path).rstrip("/") or "/"
        parent = os.path.dirname(current) or "/"
        self._go_to(parent)

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        # Importante: esto NO debe cerrar el modal ni confirmar la ruta.
        # Este evento se dispara solo por navegar/abrir una carpeta (Enter o clic),
        # y la única forma de confirmar debe ser el botón "✅ Usar esta carpeta".
        event.stop()

    def action_cancel(self) -> None:
        self.dismiss(None)


class NavajaSuizaLogsApp(App):
    """App principal: generación y exploración de resúmenes de errores del sistema."""

    CSS = """
    #top-row { height: auto; padding: 1 0; }
    #top-row Input { width: 18; margin-right: 1; }
    #buscador { width: 32; }
    #quick-row { height: auto; padding-bottom: 1; }
    #ruta_label { padding: 1; color: $text-muted; }
    #picker-box {
        width: 80%;
        height: 85%;
        border: round $accent;
        padding: 1;
        background: $panel;
    }
    #picker-help { color: $text-muted; padding-bottom: 1; }
    #current-path-label { color: $accent; padding-bottom: 1; }
    #path-input { margin-bottom: 1; }
    #picker-shortcuts { height: auto; padding-bottom: 1; }
    #picker-shortcuts Button { margin-right: 1; }
    #dir-tree { height: 1fr; }
    DataTable { height: 1fr; margin-bottom: 1; }
    #bottom-row { height: auto; }
    """

    BINDINGS = [("q", "quit", "Salir")]

    def __init__(self):
        super().__init__()
        self.current_save_path = os.getcwd()
        self.selected_entry = None
        self.row_map = {}
        log_engine.register_path(self.current_save_path)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="top-row"):
            yield Input(placeholder="Fecha Inicio (AAAA-MM-DD)", id="fecha_i")
            yield Input(placeholder="Fecha Fin (AAAA-MM-DD)", id="fecha_f")
            yield Input(placeholder="Hora Inicio (HH:MM)", id="hora_i", value="00:00")
            yield Input(placeholder="Hora Fin (HH:MM)", id="hora_f", value="23:59")
            yield Input(placeholder="Buscar palabra clave en errores...", id="buscador")
            yield Button("⚙️ Resumir Log", id="btn_resumir", variant="primary")
        with Horizontal(id="quick-row"):
            yield Button("Hoy", id="btn_hoy")
            yield Button("Ayer", id="btn_ayer")
            yield Button("Últimas 24h", id="btn_24h")
            yield Static(f"Ruta actual: {self.current_save_path}", id="ruta_label")
        yield DataTable(id="tabla_logs", cursor_type="row", zebra_stripes=True)
        with Horizontal(id="bottom-row"):
            yield Button("📂 Abrir Seleccionado", id="btn_abrir")
            yield Button("📁 Cambiar Ruta", id="btn_cambiar_ruta")
            yield Button("🔄 Refrescar Lista", id="btn_refrescar")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#tabla_logs", DataTable)
        table.add_columns("Archivo", "Ruta", "Fecha de Modificación")
        self.refresh_list()

    # --- LISTA DE LOGS ---
    def refresh_list(self) -> None:
        table = self.query_one("#tabla_logs", DataTable)
        table.clear()
        self.row_map = {}
        self.selected_entry = None
        entries = log_engine.find_all_logs()
        if not entries:
            self.notify("No hay logs generados todavía.", severity="information")
            return
        for entry in entries:
            fecha = datetime.datetime.fromtimestamp(entry["mtime"]).strftime('%Y-%m-%d %H:%M:%S')
            key = table.add_row(entry["name"], entry["path"], fecha, key=entry["full_path"])
            self.row_map[key.value] = entry

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        # Selección inmediata con clic o flechas, sin necesitar Enter.
        if event.row_key is not None and event.row_key.value in self.row_map:
            self.selected_entry = self.row_map[event.row_key.value]

    # --- BOTONES ---
    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn_resumir":
            self.run_summary()
        elif bid == "btn_abrir":
            self.open_selected_file()
        elif bid == "btn_refrescar":
            self.refresh_list()
        elif bid == "btn_cambiar_ruta":
            self.run_worker(self.change_path(), exclusive=True)
        elif bid == "btn_hoy":
            self.fill_quick_range(days=0)
        elif bid == "btn_ayer":
            self.fill_quick_range(days=1)
        elif bid == "btn_24h":
            self.fill_last_24h()

    def fill_quick_range(self, days: int) -> None:
        target = datetime.date.today() - datetime.timedelta(days=days)
        self.query_one("#fecha_i", Input).value = target.strftime('%Y-%m-%d')
        self.query_one("#fecha_f", Input).value = target.strftime('%Y-%m-%d')
        self.query_one("#hora_i", Input).value = "00:00"
        self.query_one("#hora_f", Input).value = "23:59"

    def fill_last_24h(self) -> None:
        now = datetime.datetime.now()
        yesterday = now - datetime.timedelta(days=1)
        self.query_one("#fecha_i", Input).value = yesterday.strftime('%Y-%m-%d')
        self.query_one("#fecha_f", Input).value = now.strftime('%Y-%m-%d')
        self.query_one("#hora_i", Input).value = yesterday.strftime('%H:%M')
        self.query_one("#hora_f", Input).value = now.strftime('%H:%M')

    # --- ACCIONES CORE ---
    def run_summary(self) -> None:
        fecha_i = self.query_one("#fecha_i", Input).value.strip()
        fecha_f = self.query_one("#fecha_f", Input).value.strip()
        hora_i = self.query_one("#hora_i", Input).value.strip() or "00:00"
        hora_f = self.query_one("#hora_f", Input).value.strip() or "23:59"
        buscador = self.query_one("#buscador", Input).value.strip()

        if not fecha_i and not fecha_f:
            self.notify("Ingresa una Fecha de Inicio y una Fecha de Fin.", severity="error")
            return
        if not fecha_i:
            self.notify("Ingresa una Fecha de Inicio.", severity="error")
            return
        if not fecha_f:
            self.notify("Ingresa una Fecha de Fin.", severity="error")
            return
        if not os.path.exists(self.current_save_path):
            self.notify("La ruta de guardado no es válida. Cambia de ruta primero.", severity="error")
            return

        start_datetime = f"{fecha_i} {hora_i}:00"
        end_datetime = f"{fecha_f} {hora_f}:00"

        try:
            log_engine.generate_report(
                start=start_datetime,
                end=end_datetime,
                path=self.current_save_path,
                keyword=buscador if buscador else None,
            )
            self.refresh_list()
            self.notify("Resumen generado exitosamente.", severity="information")
        except Exception as err:
            self.notify(f"Error interno: {err}", severity="error")

    def open_selected_file(self) -> None:
        if not self.selected_entry:
            self.notify("Primero selecciona un log en la lista.", severity="error")
            return

        filepath = self.selected_entry["full_path"]
        try:
            if os.name == "nt":
                os.startfile(filepath)  # noqa: S606 (uso intencional en Windows)
            else:
                subprocess.Popen(["xdg-open", filepath])
        except Exception as err:
            self.notify(f"No se pudo abrir el archivo: {err}", severity="error")

    async def change_path(self) -> None:
        result = await self.push_screen_wait(DirectoryPickerScreen(self.current_save_path))
        if result:
            self.current_save_path = result
            log_engine.register_path(result)
            self.query_one("#ruta_label", Static).update(f"Ruta actual: {result}")
            self.refresh_list()
            self.notify(f"Ruta configurada: {result}")


if __name__ == "__main__":
    NavajaSuizaLogsApp().run()