import sys


def main() -> int:
    # `python -m goveehome` opens the GUI, `python -m goveehome <command>`
    # behaves like goveehome-cli.
    if len(sys.argv) > 1:
        from goveehome.cli import main as cli_main
        return cli_main()
    from goveehome.ui.app import main as gui_main
    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
