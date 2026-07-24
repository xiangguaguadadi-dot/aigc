"""Small terminal client for checking or scripting the live robot server."""

from __future__ import annotations

import argparse
import socket
import threading
import time

from simulation.scripts.command_robot import _split_commands
from simulation.streaming.protocol import decode_message, encode_message


TERMINAL_STATUSES = {"completed", "cancelled", "failed"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Send commands to a running live robot server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--commands", default="status")
    parser.add_argument("--move-to", default=None, help="Optional end-effector target x,y,z")
    parser.add_argument("--stop-after", type=float, default=None, help="Stop the first command after N seconds")
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    with socket.create_connection((args.host, args.port), timeout=args.timeout) as connection:
        connection.settimeout(args.timeout)
        reader = connection.makefile("rb")
        hello = _wait_for_type(reader, "hello", args.timeout)
        print(
            f"Connected: protocol={hello['protocol_version']} "
            f"robot={hello['scene']['robot']['type']} stream={hello['stream_fps']}fps"
        )

        for index, command in enumerate(_split_commands(args.commands)):
            request_id = f"cli-{index + 1}-{int(time.time() * 1000)}"
            connection.sendall(encode_message({"type": "command", "id": request_id, "text": command}))
            timer = None
            if index == 0 and args.stop_after is not None:
                timer = threading.Timer(
                    args.stop_after,
                    lambda: connection.sendall(encode_message({"type": "stop"})),
                )
                timer.start()
            result, states = _wait_for_result(reader, request_id, args.timeout)
            if timer is not None:
                timer.cancel()
            print(f"Command {command!r}: {result['status']} ({states} state frames)")

        if args.move_to:
            target = [float(value.strip()) for value in args.move_to.split(",")]
            if len(target) != 3:
                parser.error("--move-to must be x,y,z")
            request_id = f"cli-move-{int(time.time() * 1000)}"
            connection.sendall(
                encode_message(
                    {"type": "action", "id": request_id, "action": "move_to", "target": target}
                )
            )
            result, states = _wait_for_result(reader, request_id, args.timeout)
            print(f"Move to {target}: {result['status']} ({states} state frames)")


def _wait_for_type(reader, expected_type: str, timeout: float):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        message = _read_message(reader)
        if message.get("type") == expected_type:
            return message
        if message.get("type") in {"error", "server_error"}:
            raise RuntimeError(message.get("error", "Server error"))
    raise TimeoutError(f"Timed out waiting for {expected_type}")


def _wait_for_result(reader, request_id: str, timeout: float):
    deadline = time.monotonic() + timeout
    state_count = 0
    while time.monotonic() < deadline:
        message = _read_message(reader)
        if message.get("type") == "state":
            state_count += 1
        elif (
            message.get("type") == "result"
            and message.get("id") == request_id
            and message.get("status") in TERMINAL_STATUSES
        ):
            return message, state_count
        elif message.get("type") in {"error", "server_error"}:
            raise RuntimeError(message.get("error", "Server error"))
    raise TimeoutError(f"Timed out waiting for command {request_id}")


def _read_message(reader):
    line = reader.readline()
    if not line:
        raise ConnectionError("Robot server disconnected")
    return decode_message(line)


if __name__ == "__main__":
    main()
