#!/usr/bin/env python3
"""
Hot Wheels Portal Live Dashboard

A beautiful terminal UI for viewing real-time lap times and speed data.
"""

import asyncio
import struct
import sys
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich.align import Align
from rich import box
import math

from hwportal import HotWheelsPortal
from hwportal.constants import (
    CHAR_EVENT_1, CHAR_EVENT_2, CHAR_EVENT_3,
    CHAR_CONTROL, CHAR_SERIAL_NUMBER
)


@dataclass
class CarStats:
    """Statistics for a single car."""
    nfc_uid: str
    serial: str = ""
    name: str = ""
    laps: int = 0
    speeds: list = field(default_factory=list)
    lap_times: list = field(default_factory=list)
    best_speed: float = 0.0
    best_lap: float = float('inf')
    last_seen: datetime = field(default_factory=datetime.now)


class Dashboard:
    def __init__(self):
        self.console = Console()
        self.portal: HotWheelsPortal | None = None

        # Current state
        self.current_car: CarStats | None = None
        self.car_database: dict[str, CarStats] = {}
        self.last_pass_time: datetime | None = None

        # Session stats
        self.session_start = datetime.now()
        self.total_passes = 0
        self.recent_passes: list[dict] = []  # Last 10 passes

        # For live display
        self.status_message = "Waiting for portal..."
        self.connected = False

    def get_car(self, nfc_uid: str) -> CarStats:
        """Get or create car stats."""
        if nfc_uid not in self.car_database:
            self.car_database[nfc_uid] = CarStats(nfc_uid=nfc_uid)
        return self.car_database[nfc_uid]

    def handle_event(self, event):
        """Handle portal events."""
        data = event.data

        if event.characteristic == CHAR_EVENT_2:
            # Car detection
            if len(data) >= 7:
                nfc_uid = ":".join(f"{b:02X}" for b in data[1:7])
                self.current_car = self.get_car(nfc_uid)
                self.current_car.last_seen = datetime.now()
                self.status_message = f"Car detected: {nfc_uid[:11]}..."
            elif len(data) == 0:
                self.current_car = None
                self.status_message = "No car on portal"

        elif event.characteristic == CHAR_SERIAL_NUMBER:
            # Car serial
            if len(data) > 0 and self.current_car:
                self.current_car.serial = data.decode('utf-8', errors='replace')

        elif event.characteristic == CHAR_EVENT_3:
            # Speed data
            if len(data) >= 4:
                speed = struct.unpack('<f', data[:4])[0]
                scale_speed = speed * 64  # Scale to "real world" equivalent

                now = datetime.now()

                # Calculate lap time if we have a previous pass
                lap_time = None
                if self.last_pass_time:
                    lap_time = (now - self.last_pass_time).total_seconds()

                self.last_pass_time = now
                self.total_passes += 1

                # Update car stats
                if self.current_car:
                    self.current_car.speeds.append(scale_speed)
                    self.current_car.laps += 1

                    if scale_speed > self.current_car.best_speed:
                        self.current_car.best_speed = scale_speed

                    if lap_time and lap_time < self.current_car.best_lap:
                        self.current_car.best_lap = lap_time

                    if lap_time:
                        self.current_car.lap_times.append(lap_time)

                # Add to recent passes
                self.recent_passes.append({
                    "time": now,
                    "car": self.current_car.nfc_uid[:8] if self.current_car else "Unknown",
                    "speed": scale_speed,
                    "lap_time": lap_time,
                })

                # Keep only last 10
                self.recent_passes = self.recent_passes[-10:]

                self.status_message = f"Pass #{self.total_passes}: {scale_speed:.1f} mph"

    def create_speed_bar(self, speed: float, max_speed: float = 150) -> Text:
        """Create a visual speed bar."""
        bar_width = 20
        filled = int((speed / max_speed) * bar_width)
        filled = min(filled, bar_width)

        # Color based on speed
        if speed < 50:
            color = "yellow"
        elif speed < 80:
            color = "green"
        elif speed < 100:
            color = "cyan"
        else:
            color = "red"

        bar = "█" * filled + "░" * (bar_width - filled)
        text = Text()
        text.append(bar, style=color)
        text.append(f" {speed:.1f} mph", style="bold white")
        return text

    def create_speedometer(self, speed: float, max_speed: float = 150) -> Text:
        """Create a visual speedometer gauge like a car dashboard."""
        # Clamp speed
        speed = max(0, min(speed, max_speed))

        # Determine color based on speed zones
        if speed < 50:
            speed_color = "green"
            zone = "🟢"
        elif speed < 80:
            speed_color = "yellow"
            zone = "🟡"
        elif speed < 100:
            speed_color = "orange1"
            zone = "🟠"
        else:
            speed_color = "red"
            zone = "🔴"

        # Calculate needle position (0-150 mph maps to gauge positions)
        # The gauge goes from left to right
        needle_pos = int((speed / max_speed) * 28)  # 28 positions across the gauge

        # Build the speedometer ASCII art
        lines = []

        # Top decorative line with flames at high speed
        if speed >= 100:
            lines.append(("      🔥🔥🔥 BLAZING FAST! 🔥🔥🔥", "bold red"))
        elif speed >= 80:
            lines.append(("          ⚡ HIGH SPEED! ⚡", "bold orange1"))
        else:
            lines.append(("", ""))

        # Gauge top arc
        lines.append(("        ╭─────────────────────────────╮", "bright_black"))

        # Speed markings row
        lines.append(("      ╱  0    40    80   120   150  ╲", "bright_black"))

        # Create the needle row
        gauge_line = list("     ╱ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ╲")

        # Fill in color zones
        zone_colors = []
        for i in range(28):
            pos_speed = (i / 28) * max_speed
            if pos_speed < 50:
                zone_colors.append("green")
            elif pos_speed < 80:
                zone_colors.append("yellow")
            elif pos_speed < 100:
                zone_colors.append("orange1")
            else:
                zone_colors.append("red")

        # Gauge with colored zones
        lines.append(("     ╱ ", "bright_black"))

        # The arc bottom
        lines.append(("     ╰────────────────────────────────╯", "bright_black"))

        # Needle indicator
        needle_line = "              " + " " * needle_pos + "▲"
        lines.append((needle_line, speed_color))

        # Big speed display
        speed_str = f"{speed:.0f}"
        lines.append(("", ""))
        lines.append((f"           ┏━━━━━━━━━━━━━┓", speed_color))
        lines.append((f"           ┃  {speed_str:^7}  ┃", f"bold {speed_color}"))
        lines.append((f"           ┃     MPH     ┃", speed_color))
        lines.append((f"           ┗━━━━━━━━━━━━━┛", speed_color))

        # Build the Text object with colors
        text = Text()

        # Add the gauge visualization
        text.append("        ╭─────────────────────────────╮\n", style="white")
        text.append("      ╱", style="white")
        text.append("  0    40    80   120   150 ", style="dim")
        text.append(" ╲\n", style="white")

        # Colored gauge bar
        text.append("     ╱ ", style="white")
        for i in range(28):
            pos_speed = (i / 28) * max_speed
            if pos_speed < 50:
                c = "green"
            elif pos_speed < 80:
                c = "yellow"
            elif pos_speed < 100:
                c = "orange1"
            else:
                c = "red"

            if i == needle_pos:
                text.append("▼", style=f"bold white on {c}")
            else:
                text.append("━", style=c)
        text.append(" ╲\n", style="white")

        text.append("     ╰────────────────────────────────╯\n", style="white")

        # Needle pointer below
        text.append("       " + " " * needle_pos + "┃\n", style=f"bold {speed_color}")
        text.append("       " + " " * needle_pos + "┃\n", style=f"bold {speed_color}")

        # Speed display box
        text.append("\n")

        # Add flames/effects for high speed
        if speed >= 100:
            text.append("         🔥", style="red")
            text.append(f"  {speed:.0f}  ", style=f"bold {speed_color} reverse")
            text.append("🔥\n", style="red")
            text.append("            MPH\n", style=f"bold {speed_color}")
            text.append("       🏁 RECORD SPEED! 🏁\n", style="bold white")
        elif speed >= 80:
            text.append("         ⚡", style="yellow")
            text.append(f"  {speed:.0f}  ", style=f"bold {speed_color} reverse")
            text.append("⚡\n", style="yellow")
            text.append("            MPH\n", style=f"bold {speed_color}")
        else:
            text.append(f"          {speed:.0f}\n", style=f"bold {speed_color}")
            text.append("            MPH\n", style=f"{speed_color}")

        return text

    def create_speedometer_panel(self, speed: float) -> Panel:
        """Create the full speedometer panel with title."""
        speedo = self.create_speedometer(speed)
        return Panel(
            Align.center(speedo),
            title="🏎️ SPEEDOMETER",
            border_style="bright_blue",
            padding=(0, 1)
        )

    def build_display(self) -> Layout:
        """Build the dashboard layout with prominent speedometer."""
        layout = Layout()

        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="footer", size=3),
        )

        # Split main into speedometer (center) and side panels
        layout["main"].split_row(
            Layout(name="left", ratio=1),
            Layout(name="center", ratio=2),
            Layout(name="right", ratio=1),
        )

        # Header
        header_text = Text()
        header_text.append("🏎️  HOT WHEELS PORTAL DASHBOARD  🏎️", style="bold magenta")
        layout["header"].update(Panel(header_text, style="magenta"))

        # Get current speed for speedometer
        current_speed = 0.0
        if self.current_car and self.current_car.speeds:
            current_speed = self.current_car.speeds[-1]
        elif self.recent_passes:
            current_speed = self.recent_passes[-1]["speed"]

        # CENTER: Big speedometer
        layout["center"].update(self.create_speedometer_panel(current_speed))

        # LEFT: Current car info
        if self.current_car:
            car = self.current_car
            car_info = Table(show_header=False, box=None, padding=(0, 1))
            car_info.add_column("Label", style="dim")
            car_info.add_column("Value", style="bold")

            # Shorter UID display
            short_uid = car.nfc_uid[:11] + "..."
            car_info.add_row("🚗 Car:", short_uid)
            car_info.add_row("🔢 Serial:", car.serial or "—")
            car_info.add_row("", "")
            car_info.add_row("🏁 Laps:", str(car.laps))
            car_info.add_row("⚡ Best:", f"{car.best_speed:.0f} mph")

            if car.best_lap < float('inf'):
                car_info.add_row("⏱️ Best Lap:", f"{car.best_lap:.2f}s")

            if car.lap_times:
                avg_lap = sum(car.lap_times) / len(car.lap_times)
                car_info.add_row("📊 Avg Lap:", f"{avg_lap:.2f}s")

            layout["left"].update(Panel(car_info, title="CAR INFO", border_style="green"))
        else:
            no_car_text = Text()
            no_car_text.append("\n\n", style="")
            no_car_text.append("  🚗\n", style="dim")
            no_car_text.append("\n  Place car\n", style="dim italic")
            no_car_text.append("  on portal\n", style="dim italic")
            layout["left"].update(Panel(no_car_text, title="CAR INFO", border_style="dim"))

        # RIGHT: Recent passes (compact)
        passes_table = Table(box=None, padding=(0, 0), show_header=True)
        passes_table.add_column("#", style="dim", width=3)
        passes_table.add_column("Speed", width=8)
        passes_table.add_column("Lap", width=6)

        for i, p in enumerate(reversed(self.recent_passes[-6:]), 1):
            if p["speed"] >= 100:
                speed_style = "bold red"
                icon = "🔥"
            elif p["speed"] >= 80:
                speed_style = "bold orange1"
                icon = "⚡"
            else:
                speed_style = "green"
                icon = "  "

            lap_str = f"{p['lap_time']:.1f}s" if p['lap_time'] else "—"
            passes_table.add_row(
                f"{icon}",
                Text(f"{p['speed']:.0f}", style=speed_style),
                lap_str,
            )

        layout["right"].update(Panel(passes_table, title="HISTORY", border_style="blue"))

        # Footer - status and session info
        session_duration = datetime.now() - self.session_start
        minutes = int(session_duration.total_seconds() // 60)
        seconds = int(session_duration.total_seconds() % 60)

        footer_text = Text()
        footer_text.append(f"Status: {self.status_message}", style="bold")
        footer_text.append(f"  │  Session: {minutes}m {seconds}s", style="dim")
        footer_text.append(f"  │  Passes: {self.total_passes}", style="dim")
        footer_text.append(f"  │  Cars: {len(self.car_database)}", style="dim")
        footer_text.append("  │  Ctrl+C to exit", style="dim italic")

        layout["footer"].update(Panel(footer_text, style="dim"))

        return layout

    async def run(self, address: str | None = None):
        """Run the dashboard."""
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
                self.connected = True

                info = await portal.get_info()
                self.status_message = f"Connected - FW {info.firmware_version}"

                # Subscribe to events
                portal.on_event(self.handle_event)
                await portal.start_monitoring()

                # Live display
                with Live(self.build_display(), refresh_per_second=4, console=self.console) as live:
                    try:
                        while True:
                            live.update(self.build_display())
                            await asyncio.sleep(0.25)
                    except KeyboardInterrupt:
                        pass

                # Show final stats
                self.show_session_summary()

        except Exception as e:
            self.console.print(f"[red]Error: {e}[/red]")

    def show_session_summary(self):
        """Show session summary at exit."""
        self.console.print("\n")
        self.console.rule("[bold magenta]Session Summary[/bold magenta]")

        if not self.car_database:
            self.console.print("[dim]No cars detected this session[/dim]")
            return

        # Summary table
        table = Table(title="Car Statistics", box=box.ROUNDED)
        table.add_column("NFC UID", style="cyan")
        table.add_column("Serial")
        table.add_column("Laps", justify="right")
        table.add_column("Best Speed", justify="right")
        table.add_column("Best Lap", justify="right")
        table.add_column("Avg Speed", justify="right")

        for car in self.car_database.values():
            avg_speed = sum(car.speeds) / len(car.speeds) if car.speeds else 0
            best_lap = f"{car.best_lap:.2f}s" if car.best_lap < float('inf') else "—"

            table.add_row(
                car.nfc_uid,
                car.serial or "—",
                str(car.laps),
                f"{car.best_speed:.1f} mph",
                best_lap,
                f"{avg_speed:.1f} mph",
            )

        self.console.print(table)
        self.console.print(f"\n[dim]Total passes: {self.total_passes}[/dim]")


async def main():
    address = sys.argv[1] if len(sys.argv) > 1 else None
    dashboard = Dashboard()
    await dashboard.run(address)


if __name__ == "__main__":
    asyncio.run(main())
