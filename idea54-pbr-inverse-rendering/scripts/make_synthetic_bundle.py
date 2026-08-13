from idea54.cli import main

raise SystemExit(main(["make-synthetic", *__import__("sys").argv[1:]]))
