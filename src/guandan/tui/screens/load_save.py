"""断点续局屏。"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from ...storage import has_savegame, load_game


class LoadSaveScreen(Screen):
    """断点续局屏（加载/删除存档）。"""

    BINDINGS = [
        ("escape", "back", "返回"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)

        if not has_savegame():
            with Center():
                with Vertical(id="load-box"):
                    yield Static("💾 断点续局", id="load-title")
                    yield Static("暂无存档", id="load-empty")
                    yield Static("退出未完成的对局时会自动保存", id="load-hint")
                    yield Button("← 返回", id="btn-back")
        else:
            savegame = load_game()
            if savegame:
                with Center():
                    with Vertical(id="load-box"):
                        yield Static("💾 断点续局", id="load-title")
                        yield Static(f"存档时间：{savegame['saved_at'][:19]}")
                        yield Static(f"级牌：{savegame['metadata']['level']}")
                        yield Static(f"已进行：{len(savegame['events'])} 步")
                        yield Static(f"手牌剩余：{savegame['current_state_snapshot']['hand_sizes']}")
                        yield Button("继续游戏", id="btn-continue")
                        yield Button("删除存档", id="btn-delete", variant="error")
                        yield Button("← 返回", id="btn-back")
            else:
                with Center():
                    with Vertical(id="load-box"):
                        yield Static("💾 断点续局", id="load-title")
                        yield Static("存档文件损坏", id="load-error")
                        yield Button("← 返回", id="btn-back")

        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#load-title", Static).styles.text_style = "bold"
        self.query_one("#load-title", Static).styles.color = "yellow"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-continue":
            # TODO: 实现加载游戏逻辑（需要 GameScreen 支持）
            self.app.push_screen(
                Static("加载存档功能待实现（需要 GameScreen 集成）")
            )
        elif event.button.id == "btn-delete":
            from ...storage import delete_savegame

            delete_savegame()
            self.app.pop_screen()
        else:
            self.app.pop_screen()

    def action_back(self) -> None:
        self.app.pop_screen()
