from idea54.cli import main

raise SystemExit(main(["run-paired", *__import__("sys").argv[1:]]))
