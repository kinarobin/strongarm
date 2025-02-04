import argparse
import logging
import pathlib
import sys
from typing import List, Text

from strongarm.cli.utils import (
    disassemble_function,
    disassemble_method,
    pick_macho_slice,
    print_analyzer_classes,
    print_analyzer_exported_symbols,
    print_analyzer_imported_symbols,
    print_analyzer_methods,
    print_analyzer_protocols,
    print_binary_info,
    print_binary_load_commands,
    print_binary_sections,
    print_binary_segments,
    print_raw_strings,
    print_selector,
)
from strongarm.debug_util import DebugUtil
from strongarm.macho import MachoAnalyzer, MachoBinary, MachoParser, VirtualMemoryPointer


def print_header(args: argparse.Namespace) -> None:
    header_lines = ["\nstrongarm - Mach-O analyzer", f"{args.binary_path}"]
    # find longest line
    longest_line_len = 0
    for line in header_lines:
        longest_line_len = max(longest_line_len, len(line))
    # add a line of hyphens, where the hyphen count matches the longest line
    header_lines.append("-" * longest_line_len)
    header_lines.append("")

    # print header
    for line in header_lines:
        print(line)


class InfoCommand:
    def __init__(self, binary: MachoBinary, analyzer: MachoAnalyzer):
        self.binary = binary
        self.analyzer = analyzer

        self.commands = {
            "all": (self.run_all_commands, None),
            "metadata": (print_binary_info, self.binary),
            "segments": (print_binary_segments, self.binary),
            "sections": (print_binary_sections, self.binary),
            "loads": (print_binary_load_commands, self.binary),
            "classes": (print_analyzer_classes, self.analyzer),
            "protocols": (print_analyzer_protocols, self.analyzer),
            "methods": (print_analyzer_methods, self.analyzer),
            "imports": (print_analyzer_imported_symbols, self.analyzer),
            "exports": (print_analyzer_exported_symbols, self.analyzer),
            "strings": (print_raw_strings, self.binary),
        }

    def description(self) -> str:
        return "Read binary information. info " + " ".join(f"[{cmd}]" for cmd in self.commands)

    def run_all_commands(self) -> None:
        for cmd in self.commands:
            if cmd == "all":
                continue
            self.run_command(cmd)

    def run_command(self, cmd: Text) -> None:
        if cmd == "all":
            self.run_all_commands()
            return

        if cmd not in self.commands:
            print(f"Unknown argument supplied to info: {cmd}")
            return

        func, arg = self.commands[cmd]
        func(arg)  # type: ignore


class StrongarmShell:
    def __init__(self, binary: MachoBinary, analyzer: MachoAnalyzer):
        self.binary = binary
        self.analyzer = analyzer

        self.commands = {
            "help": ("Display available commands", self.help),
            "exit": ("Exit interactive shell", self.exit),
            "info": (InfoCommand(self.binary, self.analyzer).description(), self.info),
            "sels": ("List selectors implemented by a class. sels [class]", self.selectors),
            "disasm": ("Decompile a given selector. disasm [sel]", self.disasm),
            "disasm_f": ("Decompile a given selector. disasm [sel]", self.disasm_f),
            "dump": ("Hex dump a memory address. dump [size] [virtual address]", self.dump_memory),
        }
        print("strongarm interactive shell")
        print("Type 'help' for available commands.")
        self.active = True

    def dump_memory(self, args: List[str]) -> None:
        def err() -> None:
            print("Usage: dump [size] [virtual address]")
            return

        if len(args) < 2:
            return err()
        try:
            dump_size = int(args[0], 10)
            address = int(args[1], 16)
        except ValueError as e:
            print(f"Failed to interpret address: {e}")
            return err()

        binary_data = self.binary.get_content_from_virtual_address(VirtualMemoryPointer(address), dump_size)

        # split to 16 byte regions
        region_size = 16
        current_index = 0
        while True:
            if current_index >= dump_size:
                break
            # grab the next grouping of bytes
            byte_region = binary_data[current_index : current_index + region_size]

            region_start = address + current_index
            region_start_str = hex(region_start)
            print(region_start_str, end="\t\t")

            ascii_rep = "|"
            for idx, byte in enumerate(byte_region):
                print("{:02x}".format(byte), end=" ")
                # indent every 8 bytes
                if idx > 0 and (idx + 1) % 8 == 0:
                    print("\t", end="")

                ascii_byte = chr(byte) if 32 <= byte < 127 else "."
                ascii_rep += ascii_byte
            ascii_rep += "|"
            print(ascii_rep)

            current_index += region_size

    def selectors(self, args: List[str]) -> None:
        if not len(args):
            print("Usage: sels [class]")
            return

        class_name = args[0]
        objc_classes = [x for x in self.analyzer.objc_classes() if x.name == class_name]
        if not len(objc_classes):
            print(f"Unknown class '{class_name}'. Run 'info classes' for a list of implemented classes.")
            return

        objc_class = objc_classes[0]
        for sel in objc_class.selectors:
            print_selector(objc_class, sel)

    def disasm(self, args: List[str]) -> None:
        if not len(args):
            print("Usage: disasm [sel]")
            return

        sel_name = args[0]
        matching_sels = [x for x in self.analyzer.get_objc_methods() if x.objc_sel.name == sel_name]
        if not len(matching_sels):
            print(f"Unknown selector '{sel_name}'. Run 'info methods' for a list of selectors.")
            return

        disassembled_str = disassemble_method(self.binary, matching_sels[0])
        print(disassembled_str)

    def disasm_f(self, args: List[str]) -> None:
        if not len(args):
            print("Usage: disasm [sel]")
            return

        disassembled_str = disassemble_function(self.binary, VirtualMemoryPointer(args[0], 16))
        print(disassembled_str)

    def help(self, _args: List[str]) -> None:
        print("Commands")
        print("----------------")
        for name, (description, funcptr) in self.commands.items():
            print(f"{name}: {description}")

    def info(self, args: List[str]) -> None:
        info_cmd = InfoCommand(self.binary, self.analyzer)
        if not len(args):
            print("No option provided")
            print(info_cmd.description())
        for option in args:
            info_cmd.run_command(option)

    def exit(self, _args: List[str]) -> None:
        print("Quitting...")
        self.active = False

    def run_command(self, user_input: Text) -> bool:
        components = user_input.split(" ")
        cmd_name = components[0]
        cmd_args = components[1:]

        if cmd_name not in self.commands:
            print(f"Unknown command: '{cmd_name}'. Type 'help' for available commands.")
            return self.active

        func = self.commands[cmd_name][1]
        func(cmd_args)
        return self.active

    def process_command(self) -> bool:
        user_input = input("strongarm$ ")
        return self.run_command(user_input)


def strongarm_script(binary: MachoBinary, analyzer: MachoAnalyzer) -> None:
    """If you want to run a script instead of using the CLI, write it here and change `script` to `True` in main()
    """


def main() -> None:
    # XXX(PT): Change this if you want to run a quick script! Write it in strongarm_script()
    script = False
    # end of config

    arg_parser = argparse.ArgumentParser(description="Mach-O Analyzer")
    arg_parser.add_argument("--verbose", action="store_true", help="Output extra info while analyzing")
    arg_parser.add_argument("binary_path", metavar="binary_path", type=str, help="Path to binary to analyze")
    args = arg_parser.parse_args()

    def configure_logger() -> None:
        root = logging.getLogger()
        root.setLevel(logging.DEBUG)

        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        ch.setFormatter(formatter)
        root.addHandler(ch)

    configure_logger()

    if args.verbose:
        DebugUtil.debug = True

    print_header(args)

    parser = MachoParser(pathlib.Path(args.binary_path))

    # print slice info
    print("Slices:")
    for macho_slice in parser.slices:
        print(f"\t{macho_slice.cpu_type.name} Mach-O slice")

    binary = pick_macho_slice(parser)
    print(f"Reading {binary.cpu_type.name} slice\n\n")

    analyzer = MachoAnalyzer.get_analyzer(binary)
    shell = StrongarmShell(binary, analyzer)

    if script:
        print("Running provided script...\n\n")
        strongarm_script(binary, analyzer)
    else:
        autorun_cmd = "info metadata segments sections loads"
        print(f"Auto-running '{autorun_cmd}'\n\n")
        shell.run_command(autorun_cmd)

        # this will return False once the shell exists
        while shell.process_command():
            pass
    print("May your arms be beefy and your binaries unencrypted")


if __name__ == "__main__":
    main()
