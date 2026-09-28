from idea54.cli import main

raise SystemExit(main(["report", *__import__("sys").argv[1:]]))
