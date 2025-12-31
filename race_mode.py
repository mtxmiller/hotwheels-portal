#!/usr/bin/env python3
"""
Hot Wheels Portal - Lap Race Game Mode

A competitive racing game where players complete a set number of laps
and compare their times.
"""

import asyncio
import struct
import sys
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum, auto

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.layout import Layout
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich import box

from hwportal import HotWheelsPortal
from hwportal.constants import CHAR_EVENT_2, CHAR_EVENT_3, CHAR_SERIAL_NUMBER


class GameState(Enum):
    MENU = auto()
    SETUP = auto()
    COUNTDOWN = auto()
    RACING = auto()
    FINISHED = auto()
    LEADERBOARD = auto()


@dataclass
class RaceResult:
    """Result from a single race."""
    player_name: str
    car_uid: str
    lap_count: int
    lap_times: list[float]
    total_time: float
    best_lap: float
    best_lap_num: int
    worst_lap: float
    worst_lap_num: int
    avg_lap: float
    timestamp: datetime = field(default_factory=datetime.now)


class RaceGame:
    def __init__(self):
        self.console = Console()
        self.portal: HotWheelsPortal | None = None

        # Game state
        self.state = GameState.MENU
        self.target_laps = 10
        self.current_lap = 0
        self.lap_times: list[float] = []
        self.last_lap_time: datetime | None = None
        self.race_start_time: datetime | None = None

        # Current car
        self.current_car_uid: str | None = None
        self.current_car_serial: str | None = None
        self.last_speed: float = 0.0

        # Player tracking
        self.current_player = "Player 1"
        self.player_count = 1
        self.results: list[RaceResult] = []

        # Countdown
        self.countdown_value = 3

        # UI refresh flag
        self.needs_refresh = True

    def handle_event(self, event):
        """Handle portal events."""
        data = event.data

        if event.characteristic == CHAR_EVENT_2:
            # Car detection
            if len(data) >= 7:
                self.current_car_uid = ":".join(f"{b:02X}" for b in data[1:7])
            elif len(data) == 0:
                self.current_car_uid = None

        elif event.characteristic == CHAR_SERIAL_NUMBER:
            if len(data) > 0:
                self.current_car_serial = data.decode('utf-8', errors='replace')

        elif event.characteristic == CHAR_EVENT_3:
            # Speed/lap event
            if len(data) >= 4 and self.state == GameState.RACING:
                speed = struct.unpack('<f', data[:4])[0]
                self.last_speed = speed * 64

                now = datetime.now()

                # Record lap
                if self.last_lap_time:
                    lap_time = (now - self.last_lap_time).total_seconds()
                    self.lap_times.append(lap_time)
                    self.current_lap += 1

                    # Check if race finished
                    if self.current_lap >= self.target_laps:
                        self.finish_race()

                self.last_lap_time = now
                self.needs_refresh = True

    def start_race(self):
        """Start a new race."""
        self.current_lap = 0
        self.lap_times = []
        self.last_lap_time = None
        self.race_start_time = datetime.now()
        self.state = GameState.RACING
        self.needs_refresh = True

    def finish_race(self):
        """Finish the current race and record results."""
        if not self.lap_times:
            return

        total_time = sum(self.lap_times)
        best_lap = min(self.lap_times)
        best_lap_num = self.lap_times.index(best_lap) + 1
        worst_lap = max(self.lap_times)
        worst_lap_num = self.lap_times.index(worst_lap) + 1
        avg_lap = total_time / len(self.lap_times)

        result = RaceResult(
            player_name=self.current_player,
            car_uid=self.current_car_uid or "Unknown",
            lap_count=len(self.lap_times),
            lap_times=self.lap_times.copy(),
            total_time=total_time,
            best_lap=best_lap,
            best_lap_num=best_lap_num,
            worst_lap=worst_lap,
            worst_lap_num=worst_lap_num,
            avg_lap=avg_lap,
        )
        self.results.append(result)
        self.state = GameState.FINISHED
        self.needs_refresh = True

    def create_menu_display(self) -> Panel:
        """Create the main menu display."""
        text = Text()
        text.append("\n")
        text.append("  🏁 LAP RACE MODE 🏁\n\n", style="bold magenta")
        text.append("  Race against the clock!\n", style="dim")
        text.append("  Complete laps and set records.\n\n", style="dim")
        text.append("  ─────────────────────────\n\n", style="dim")
        text.append("  [1]  5 Laps", style="bold cyan")
        text.append("   (Quick Race)\n", style="dim")
        text.append("  [2] 10 Laps", style="bold green")
        text.append("   (Standard)\n", style="dim")
        text.append("  [3] 15 Laps", style="bold yellow")
        text.append("   (Endurance)\n", style="dim")
        text.append("  [4] 20 Laps", style="bold orange1")
        text.append("   (Marathon)\n", style="dim")
        text.append("  [C] Custom\n\n", style="bold white")
        text.append("  ─────────────────────────\n\n", style="dim")
        text.append("  [L] View Leaderboard\n", style="blue")
        text.append("  [Q] Quit\n\n", style="dim")

        return Panel(
            Align.center(text),
            title="🏎️ HOT WHEELS RACE",
            border_style="magenta",
        )

    def create_countdown_display(self) -> Panel:
        """Create countdown display."""
        text = Text()
        text.append("\n\n")

        if self.countdown_value > 0:
            text.append(f"        {self.countdown_value}\n\n", style="bold yellow")
            text.append("    GET READY!\n", style="bold white")
        else:
            text.append("       GO!\n\n", style="bold green")
            text.append("    🏁 START RACING! 🏁\n", style="bold green")

        text.append(f"\n    {self.target_laps} Lap Race\n", style="dim")
        text.append(f"    Player: {self.current_player}\n", style="cyan")

        return Panel(
            Align.center(text),
            title="🚦 STARTING",
            border_style="yellow",
        )

    def create_speedometer_mini(self, speed: float) -> Text:
        """Create a mini speedometer for race mode."""
        text = Text()

        # Determine color
        if speed >= 100:
            color = "red"
            icon = "🔥"
        elif speed >= 80:
            color = "orange1"
            icon = "⚡"
        elif speed >= 50:
            color = "yellow"
            icon = ""
        else:
            color = "green"
            icon = ""

        # Speed bar
        bar_width = 20
        filled = int((speed / 150) * bar_width)
        filled = min(filled, bar_width)

        text.append("     ╭" + "─" * (bar_width + 2) + "╮\n", style="white")
        text.append("     │ ", style="white")
        for i in range(bar_width):
            if i < filled:
                pos_speed = (i / bar_width) * 150
                if pos_speed < 50:
                    text.append("█", style="green")
                elif pos_speed < 80:
                    text.append("█", style="yellow")
                elif pos_speed < 100:
                    text.append("█", style="orange1")
                else:
                    text.append("█", style="red")
            else:
                text.append("░", style="dim")
        text.append(" │\n", style="white")
        text.append("     ╰" + "─" * (bar_width + 2) + "╯\n", style="white")

        text.append(f"       {icon} {speed:.0f} MPH {icon}\n", style=f"bold {color}")

        return text

    def create_racing_display(self) -> Panel:
        """Create the racing display."""
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=5),
            Layout(name="speed", size=6),
            Layout(name="stats", size=10),
        )

        # Header with lap counter
        header = Text()
        header.append(f"\n  🏎️ LAP {self.current_lap + 1} of {self.target_laps}\n", style="bold cyan")

        # Progress bar
        progress_width = 30
        progress = int((self.current_lap / self.target_laps) * progress_width)
        header.append("  [", style="dim")
        header.append("█" * progress, style="green")
        header.append("░" * (progress_width - progress), style="dim")
        header.append("]\n", style="dim")

        layout["header"].update(Panel(header, box=box.SIMPLE))

        # Speed display
        layout["speed"].update(Panel(
            Align.center(self.create_speedometer_mini(self.last_speed)),
            box=box.SIMPLE
        ))

        # Stats
        stats = Text()
        stats.append(f"  Player: {self.current_player}\n\n", style="cyan")

        if self.lap_times:
            last_lap = self.lap_times[-1]
            best_lap = min(self.lap_times)

            # Last lap with comparison
            if last_lap == best_lap and len(self.lap_times) > 1:
                stats.append(f"  Last Lap:  {last_lap:.2f}s ", style="bold")
                stats.append("⚡ BEST!\n", style="bold green")
            else:
                diff = last_lap - best_lap
                stats.append(f"  Last Lap:  {last_lap:.2f}s ", style="bold")
                if diff > 0:
                    stats.append(f"+{diff:.2f}s\n", style="red")
                else:
                    stats.append("\n")

            stats.append(f"  Best Lap:  {best_lap:.2f}s\n", style="green")
            stats.append(f"  Total:     {sum(self.lap_times):.2f}s\n", style="dim")

            # Average
            avg = sum(self.lap_times) / len(self.lap_times)
            stats.append(f"  Average:   {avg:.2f}s\n", style="dim")
        else:
            stats.append("  Waiting for first lap...\n", style="dim italic")
            stats.append("\n  Pass through the portal!\n", style="yellow")

        layout["stats"].update(Panel(stats, box=box.SIMPLE))

        return Panel(
            layout,
            title=f"🏁 RACING - {self.target_laps} LAPS",
            border_style="green",
        )

    def create_finished_display(self) -> Panel:
        """Create the race finished display."""
        if not self.results:
            return Panel("No results", title="ERROR")

        result = self.results[-1]
        text = Text()

        text.append("\n")
        text.append("    🏁 RACE COMPLETE! 🏁\n\n", style="bold green")
        text.append(f"    Player: {result.player_name}\n\n", style="cyan")

        # Big total time
        text.append(f"    TOTAL TIME\n", style="dim")
        text.append(f"    {result.total_time:.2f}s\n\n", style="bold white")

        # Stats table
        text.append(f"    ─────────────────────\n", style="dim")
        text.append(f"    🔥 Best Lap:  {result.best_lap:.2f}s", style="green")
        text.append(f"  (Lap {result.best_lap_num})\n", style="dim")
        text.append(f"    💨 Worst Lap: {result.worst_lap:.2f}s", style="orange1")
        text.append(f"  (Lap {result.worst_lap_num})\n", style="dim")
        text.append(f"    📊 Average:   {result.avg_lap:.2f}s\n", style="white")
        text.append(f"    ─────────────────────\n\n", style="dim")

        # Lap breakdown
        text.append("    Lap Times:\n", style="dim")
        for i, lap in enumerate(result.lap_times, 1):
            if lap == result.best_lap:
                text.append(f"     {i:2d}. {lap:.2f}s ⚡\n", style="green")
            elif lap == result.worst_lap:
                text.append(f"     {i:2d}. {lap:.2f}s\n", style="orange1")
            else:
                text.append(f"     {i:2d}. {lap:.2f}s\n", style="dim")

        text.append("\n    ─────────────────────\n", style="dim")
        text.append("    [N] Next Player\n", style="cyan")
        text.append("    [R] Race Again (same player)\n", style="yellow")
        text.append("    [L] Leaderboard\n", style="blue")
        text.append("    [M] Main Menu\n", style="dim")

        return Panel(
            Align.center(text),
            title="🏆 RESULTS",
            border_style="yellow",
        )

    def create_leaderboard_display(self) -> Panel:
        """Create the leaderboard display."""
        text = Text()
        text.append("\n")
        text.append("    🏆 LEADERBOARD 🏆\n\n", style="bold yellow")

        if not self.results:
            text.append("    No races yet!\n", style="dim italic")
            text.append("    Complete a race to see results.\n", style="dim")
        else:
            # Sort by total time
            sorted_results = sorted(self.results, key=lambda r: r.total_time)

            # Create table
            table = Table(box=box.SIMPLE, padding=(0, 1))
            table.add_column("#", style="bold", width=3)
            table.add_column("Player", width=12)
            table.add_column("Laps", width=5, justify="right")
            table.add_column("Total", width=8, justify="right")
            table.add_column("Best Lap", width=8, justify="right")
            table.add_column("Avg", width=8, justify="right")

            for i, result in enumerate(sorted_results[:10], 1):
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                style = "bold yellow" if i == 1 else "bold white" if i <= 3 else ""

                table.add_row(
                    medal,
                    result.player_name,
                    str(result.lap_count),
                    f"{result.total_time:.2f}s",
                    f"{result.best_lap:.2f}s",
                    f"{result.avg_lap:.2f}s",
                    style=style,
                )

            text.append("\n")

        text.append("\n    ─────────────────────\n", style="dim")
        text.append("    [M] Main Menu\n", style="dim")
        text.append("    [C] Clear Leaderboard\n", style="red")

        content = Align.center(text)
        if self.results:
            sorted_results = sorted(self.results, key=lambda r: r.total_time)
            table = Table(box=box.ROUNDED, padding=(0, 1))
            table.add_column("#", style="bold", width=4)
            table.add_column("Player", width=12)
            table.add_column("Laps", width=5, justify="right")
            table.add_column("Total", width=9, justify="right")
            table.add_column("Best", width=8, justify="right")

            for i, result in enumerate(sorted_results[:10], 1):
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f" {i}."
                style = "bold yellow" if i == 1 else "white" if i <= 3 else "dim"

                table.add_row(
                    medal,
                    result.player_name,
                    str(result.lap_count),
                    f"{result.total_time:.2f}s",
                    f"{result.best_lap:.2f}s",
                    style=style,
                )

            from rich.console import Group
            content = Align.center(Group(text, table))

        return Panel(
            content,
            title="🏆 LEADERBOARD",
            border_style="yellow",
        )

    def build_display(self) -> Panel:
        """Build the current display based on game state."""
        if self.state == GameState.MENU:
            return self.create_menu_display()
        elif self.state == GameState.COUNTDOWN:
            return self.create_countdown_display()
        elif self.state == GameState.RACING:
            return self.create_racing_display()
        elif self.state == GameState.FINISHED:
            return self.create_finished_display()
        elif self.state == GameState.LEADERBOARD:
            return self.create_leaderboard_display()
        else:
            return Panel("Unknown state")

    async def run_countdown(self):
        """Run the countdown sequence."""
        self.state = GameState.COUNTDOWN
        for i in range(3, -1, -1):
            self.countdown_value = i
            self.needs_refresh = True
            await asyncio.sleep(1)
        self.start_race()

    async def run(self, address: str | None = None):
        """Run the race game."""
        self.console.clear()

        # Find and connect to portal
        with self.console.status("Scanning for Hot Wheels Portal..."):
            if address is None:
                portals = await HotWheelsPortal.scan(timeout=10.0)
                if not portals:
                    self.console.print("[red]No portal found![/red]")
                    return
                address = portals[0][0]

        self.console.print(f"[green]Found portal at {address}[/green]")

        try:
            async with HotWheelsPortal(address) as portal:
                self.portal = portal

                info = await portal.get_info()
                self.console.print(f"[dim]Firmware: {info.firmware_version}[/dim]")

                # Subscribe to events
                portal.on_event(self.handle_event)
                await portal.start_monitoring()

                # Main game loop
                with Live(self.build_display(), refresh_per_second=10, console=self.console) as live:
                    try:
                        while True:
                            # Handle input (non-blocking)
                            await self.handle_input()

                            # Update display
                            live.update(self.build_display())
                            await asyncio.sleep(0.1)

                    except KeyboardInterrupt:
                        pass

        except Exception as e:
            self.console.print(f"[red]Error: {e}[/red]")
            import traceback
            traceback.print_exc()

    async def handle_input(self):
        """Handle keyboard input based on current state."""
        import sys
        import select
        import tty
        import termios

        # Non-blocking input check (Unix only)
        if sys.platform != 'win32':
            # Check if input is available
            dr, _, _ = select.select([sys.stdin], [], [], 0)
            if dr:
                key = sys.stdin.read(1).lower()
                await self.process_key(key)

    async def process_key(self, key: str):
        """Process a key press."""
        if self.state == GameState.MENU:
            if key == '1':
                self.target_laps = 5
                await self.run_countdown()
            elif key == '2':
                self.target_laps = 10
                await self.run_countdown()
            elif key == '3':
                self.target_laps = 15
                await self.run_countdown()
            elif key == '4':
                self.target_laps = 20
                await self.run_countdown()
            elif key == 'c':
                # Custom - for now default to 10
                self.target_laps = 10
                await self.run_countdown()
            elif key == 'l':
                self.state = GameState.LEADERBOARD
            elif key == 'q':
                raise KeyboardInterrupt()

        elif self.state == GameState.FINISHED:
            if key == 'n':
                # Next player
                self.player_count += 1
                self.current_player = f"Player {self.player_count}"
                self.state = GameState.MENU
            elif key == 'r':
                # Race again same player
                await self.run_countdown()
            elif key == 'l':
                self.state = GameState.LEADERBOARD
            elif key == 'm':
                self.state = GameState.MENU

        elif self.state == GameState.LEADERBOARD:
            if key == 'm':
                self.state = GameState.MENU
            elif key == 'c':
                self.results = []


async def main():
    address = sys.argv[1] if len(sys.argv) > 1 else None
    game = RaceGame()
    await game.run(address)


def run_game():
    """Entry point that sets up terminal correctly."""
    import tty
    import termios
    import atexit

    # Save terminal settings
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    def restore_terminal():
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    # Restore on exit
    atexit.register(restore_terminal)

    try:
        # Set to cbreak mode (not fully raw, allows Ctrl+C)
        tty.setcbreak(fd)
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nRace ended!")
    finally:
        restore_terminal()


if __name__ == "__main__":
    run_game()
