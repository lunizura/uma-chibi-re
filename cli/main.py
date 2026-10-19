"""
main.py - Interactive Command-Line Interface for uma-chibi-pipeline.

Provides scanning, inspecting, and extracting commands for Umamusume Pretty Derby
modular 3D chibi models with rich terminal visuals.
"""

from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path
from typing import Dict, Optional

# Ensure project root is discoverable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure UTF-8 output on Windows terminal
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.text import Text

from uma_core.meta_reader import MetaDatabase
from uma_core.pipeline import ChibiPipeline


console = Console(legacy_windows=False)

# Well-known Uma character name database for friendly UI output
CHARA_NAMES: Dict[str, str] = {
    "1001": "Special Week",
    "1002": "Silence Suzuka",
    "1003": "Tokai Teio",
    "1004": "Maruzensky",
    "1005": "Fuji Kiseki",
    "1006": "Oguri Cap",
    "1007": "Gold Ship",
    "1008": "Vodka",
    "1009": "Daiwa Scarlet",
    "1010": "Taiki Shuttle",
    "1011": "Grass Wonder",
    "1012": "Hishi Amazon",
    "1013": "Mejiro McQueen",
    "1014": "El Condor Pasa",
    "1015": "T.M. Opera O",
    "1016": "Narita Brian",
    "1017": "Symboli Rudolf",
    "1018": "Air Groove",
    "1019": "Agnes Digital",
    "1020": "Seiun Sky",
    "1021": "Tamamo Cross",
    "1022": "Fine Motion",
    "1023": "Biwa Hayahide",
    "1024": "Mayano Top Gun",
    "1025": "Manhattan Cafe",
    "1026": "Mihono Bourbon",
    "1027": "Mejiro Ryan",
    "1028": "Hishi Akebono",
    "1029": "Yukino Bijin",
    "1030": "Rice Shower",
    "1031": "Ines Fujin",
    "1032": "Agnes Tachyon",
    "1033": "Admire Vega",
    "1034": "Inari One",
    "1035": "Winning Ticket",
    "1036": "Air Shakur",
    "1037": "Eishin Flash",
    "1038": "Curren Chan",
    "1039": "Kawakami Princess",
    "1040": "Gold City",
    "1041": "Sakura Bakushin O",
    "1042": "Seek the Pearl",
    "1043": "Shinko Windy",
    "1044": "Sweep Tosho",
    "1045": "Super Creek",
    "1046": "Smart Falcon",
    "1047": "Zenno Rob Roy",
    "1048": "Tosen Jordan",
    "1049": "Nakayama Festa",
    "1050": "Narita Taishin",
    "1051": "Nishino Flower",
    "1052": "Haru Urara",
    "1053": "Bamboo Memory",
    "1054": "Biko Pegasus",
    "1055": "Marvelous Sunday",
    "1056": "Matikanefukukitaru",
    "1057": "Mr. C.B.",
    "1058": "Meisho Doto",
    "1059": "Mejiro Dober",
    "1060": "Nice Nature",
    "1061": "King Halo",
    "1062": "Matikanetannhauser",
    "1063": "Ikuno Dictus",
    "1064": "Mejiro Palmer",
    "1065": "Daitaku Helios",
    "1066": "Twin Turbo",
    "1067": "Satono Diamond",
    "1068": "Kitasan Black",
}


def print_banner():
    """Prints tool header and reverse engineering credentials banner."""
    banner = Text()
    banner.append("[*] UMA-CHIBI-PIPELINE v1.0.0 [*]\n", style="bold magenta")
    banner.append("Offline Modular 3D Asset Reverse Engineering & glTF 2.0 Pipeline\n", style="cyan")
    banner.append("AES-256-CBC Decryption | 88-Byte Rolling Keystream | UnityFS Serialization", style="dim white")
    console.print(Panel(banner, border_style="bright_blue", expand=False))


def cmd_list(args):
    """Lists all detected chibi models in local game files."""
    print_banner()
    console.print("[yellow]Connecting to encrypted SQLite metadata store (meta)...[/yellow]")

    try:
        with MetaDatabase(meta_path=args.meta) as db:
            chars = db.get_chibi_characters()
    except Exception as e:
        console.print(f"[bold red]Failed to access metadata database:[/bold red] {e}")
        sys.exit(1)

    table = Table(title=f"Discovered Chibi Characters ({len(chars)} models found)")
    table.add_column("Character ID", style="bold cyan", justify="center")
    table.add_column("Full Tag", style="dim", justify="center")
    table.add_column("Character Name", style="bright_green")
    table.add_column("Hair Bundle Hash", style="magenta")
    table.add_column("64-Bit Key (e)", style="yellow", justify="right")

    for c in chars:
        cid = c["chara_id"]
        base_id = cid.split("_")[0]
        name = CHARA_NAMES.get(base_id, f"Uma Musume #{base_id}")
        table.add_row(cid, c["tag"], name, c["hash"][:16] + "...", str(c["key"]))

    console.print(table)
    console.print(f"\n[green][OK] Successfully indexed [bold]{len(chars)}[/bold] chibi models.[/green]")
    console.print("[dim]Use `python -m cli.main extract <id>` to extract modular glTF models.[/dim]\n")


def cmd_extract(args):
    """Extracts modular GLB models for a specified character ID."""
    print_banner()
    cid = args.character_id
    base_id = cid.replace("mchr", "").split("_")[0]
    name = CHARA_NAMES.get(base_id, f"Chibi Uma #{base_id}")

    console.print(f"[bold green]Target Model:[/bold green] [bold cyan]{cid}[/bold cyan] ({name})")
    console.print(f"[dim]Output Directory: {args.out}[/dim]\n")

    pipeline = ChibiPipeline(meta_path=args.meta, data_root=args.data)
    build_assembled = not args.modular_only

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Processing asset bundles & compiling glTF...", total=None)
        try:
            results = pipeline.extract_character(
                chara_id=cid,
                output_dir=Path(args.out),
                body_id=args.body,
                tail_id=args.tail,
                build_assembled=build_assembled,
            )
            progress.update(task, completed=100, description="[green]Extraction finished!")
        except Exception as e:
            console.print(f"[bold red]Extraction failed:[/bold red] {e}")
            sys.exit(1)

    table = Table(title="Generated 3D glTF 2.0 Asset Deliverables")
    table.add_column("Modular Part", style="bold cyan")
    table.add_column("glTF Binary (.glb) File", style="white")
    table.add_column("File Size", style="green", justify="right")
    table.add_column("Compatibility", style="dim green")

    for part, path in results.items():
        size_str = f"{path.stat().st_size:,} bytes"
        table.add_row(part.capitalize(), str(path.resolve()), size_str, "Blender / Windows 3D / Unity / Godot")

    console.print(table)
    console.print(f"\n[bold green][OK] Successfully generated {len(results)} GLB files ready for 3D modeling![/bold green]\n")


def cmd_test(args):
    """Runs all automated unit and integration tests."""
    print_banner()
    console.print("[yellow]Running complete pipeline test suite...[/yellow]\n")

    loader = unittest.TestLoader()
    suite = loader.discover(str(PROJECT_ROOT / "tests"))
    runner = unittest.TextTestRunner(verbosity=2)
    res = runner.run(suite)

    if res.wasSuccessful():
        console.print("\n[bold green][OK] All automated tests passed with 100% compliance![/bold green]")
        sys.exit(0)
    else:
        console.print(f"\n[bold red][FAIL] Tests failed ({len(res.failures)} failures, {len(res.errors)} errors)[/bold red]")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="uma-chibi-pipeline",
        description="Umamusume Pretty Derby Chibi 3D Asset Reverse Engineering & Modular glTF Exporter",
    )
    parser.add_argument("--meta", help="Path to encrypted meta SQLite file", default=None)
    parser.add_argument("--data", help="Path to Persistent data directory", default=None)

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: list
    subparsers.add_parser("list", help="Scan and list all detected chibi models in local game files")

    # Subcommand: extract
    p_extract = subparsers.add_parser("extract", help="Extract modular glTF 2.0 models for a character")
    p_extract.add_argument("character_id", help="Character ID (e.g. 1001, 1007, or 1001_00)")
    p_extract.add_argument("-o", "--out", help="Output directory", default="./exports")
    p_extract.add_argument("--body", help="Body costume ID (default: auto)", default="auto")
    p_extract.add_argument("--tail", help="Tail ID", default="0001_00")
    p_extract.add_argument("--modular-only", action="store_true", help="Skip combined assembled.glb generation")

    # Subcommand: test
    subparsers.add_parser("test", help="Execute automated unit and integration test suite")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list(args)
    elif args.command == "extract":
        cmd_extract(args)
    elif args.command == "test":
        cmd_test(args)


if __name__ == "__main__":
    main()
