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

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich import box

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

    def build_display(self) -> Layout:
        """Build the dashboard layout."""
        layout = Layout()

        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="footer", size=3),
        )

        layout["main"].split_row(
            Layout(name="left", ratio=1),
            Layout(name="right", ratio=1),
        )

        # Header
        header_text = Text()
        header_text.append("🏎️  HOT WHEELS PORTAL DASHBOARD  🏎️", style="bold magenta")
        layout["header"].update(Panel(header_text, style="magenta"))

        # Current car panel (left)
        if self.current_car:
            car = self.current_car
            car_info = Table(show_header=False, box=None, padding=(0, 1))
            car_info.add_column("Label", style="dim")
            car_info.add_column("Value", style="bold")

            car_info.add_row("NFC UID:", car.nfc_uid)
            car_info.add_row("Serial:", car.serial or "—")
            car_info.add_row("Laps:", str(car.laps))

            if car.speeds:
                last_speed = car.speeds[-1]
                car_info.add_row("Last Speed:", "")
                car_info.add_row("", self.create_speed_bar(last_speed))
                car_info.add_row("Best Speed:", f"{car.best_speed:.1f} mph")

            if car.best_lap < float('inf'):
                car_info.add_row("Best Lap:", f"{car.best_lap:.2f}s")

            if car.lap_times:
                avg_lap = sum(car.lap_times) / len(car.lap_times)
                car_info.add_row("Avg Lap:", f"{avg_lap:.2f}s")

            layout["left"].update(Panel(car_info, title="🚗 Current Car", border_style="green"))
        else:
            no_car = Text("Place a car on the portal", style="dim italic", justify="center")
            layout["left"].update(Panel(no_car, title="🚗 Current Car", border_style="dim"))

        # Recent passes (right)
        passes_table = Table(box=box.SIMPLE, padding=(0, 1))
        passes_table.add_column("#", style="dim", width=4)
        passes_table.add_column("Time", width=10)
        passes_table.add_column("Car", width=10)
        passes_table.add_column("Speed", width=12)
        passes_table.add_column("Lap", width=8)

        for i, p in enumerate(reversed(self.recent_passes[-8:]), 1):
            speed_style = "green" if p["speed"] < 80 else "cyan" if p["speed"] < 100 else "red"
            lap_str = f"{p['lap_time']:.2f}s" if p['lap_time'] else "—"
            passes_table.add_row(
                str(self.total_passes - i + 1),
                p["time"].strftime("%H:%M:%S"),
                p["car"],
                Text(f"{p['speed']:.1f} mph", style=speed_style),
                lap_str,
            )

        layout["right"].update(Panel(passes_table, title="📊 Recent Passes", border_style="blue"))

        # Footer - status and session info
        session_duration = datetime.now() - self.session_start
        minutes = int(session_duration.total_seconds() // 60)
        seconds = int(session_duration.total_seconds() % 60)

        footer_text = Text()
        footer_text.append(f"Status: {self.status_message}", style="bold")
        footer_text.append(f"  │  Session: {minutes}m {seconds}s", style="dim")
        footer_text.append(f"  │  Total Passes: {self.total_passes}", style="dim")
        footer_text.append(f"  │  Cars Seen: {len(self.car_database)}", style="dim")
        footer_text.append("  │  Press Ctrl+C to exit", style="dim italic")

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
