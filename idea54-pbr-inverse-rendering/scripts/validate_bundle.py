from idea54.cli import main

raise SystemExit(main(["validate", *__import__("sys").argv[1:]]))
