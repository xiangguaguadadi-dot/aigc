"""Local TCP service that streams PyBullet Panda states to Blender."""

from __future__ import annotations

import argparse
import collections
import queue
import socket
import socketserver
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

from simulation.env import SimulationEnv
from simulation.robots.panda import PandaRobot
from simulation.scripts.command_robot import CommandCancelled, CommandScene, _parse_xyz
from simulation.streaming.protocol import (
    PROTOCOL_VERSION,
    ProtocolError,
    command_id,
    decode_message,
    encode_message,
    quaternion,
    vector3,
)
from simulation.streaming.state import capture_state, describe_scene


class ClientSession:
    """One TCP client with a non-blocking bounded outgoing queue."""

    def __init__(self, connection: socket.socket):
        self.connection = connection
        self.messages = collections.deque(maxlen=96)
        self.condition = threading.Condition()
        self.closed = False
        self.sender = threading.Thread(target=self._send_loop, daemon=True)
        self.sender.start()

    def send(self, message: dict[str, Any]) -> None:
        with self.condition:
            if self.closed:
                return
            if message.get("type") == "state" and self.messages and self.messages[-1].get("type") == "state":
                self.messages[-1] = message
            else:
                self.messages.append(message)
            self.condition.notify()

    def close(self) -> None:
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.connection.close()
        except OSError:
            pass

    def _send_loop(self) -> None:
        while True:
            with self.condition:
                while not self.messages and not self.closed:
                    self.condition.wait(timeout=1.0)
                if self.closed:
                    return
                message = self.messages.popleft()
            try:
                self.connection.sendall(encode_message(message))
            except (OSError, ProtocolError):
                self.close()
                return


class MessageBroker:
    def __init__(self):
        self._clients: set[ClientSession] = set()
        self._lock = threading.Lock()

    def add(self, client: ClientSession) -> None:
        with self._lock:
            self._clients.add(client)

    def remove(self, client: ClientSession) -> None:
        with self._lock:
            self._clients.discard(client)
        client.close()

    def broadcast(self, message: dict[str, Any]) -> None:
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            client.send(message)

    def close(self) -> None:
        with self._lock:
            clients = list(self._clients)
            self._clients.clear()
        for client in clients:
            client.close()


class LiveRobotSimulator:
    """Own PyBullet on one thread and expose command/state queues."""

    def __init__(self, args, broker: MessageBroker):
        self.args = args
        self.broker = broker
        self.ready_event = threading.Event()
        self.shutdown_event = threading.Event()
        self.command_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.thread = threading.Thread(target=self._run, name="pybullet-live", daemon=True)
        self.scene: CommandScene | None = None
        self.scene_manifest: dict[str, Any] | None = None
        self.visual_shapes: list[dict[str, Any]] = []
        self.latest_state: dict[str, Any] | None = None
        self.startup_error: str | None = None
        self._state_lock = threading.Lock()
        self._active_lock = threading.Lock()
        self._stop_lock = threading.Lock()
        self._stop_generation = 0
        self._active_command: dict[str, Any] | None = None
        self._physics_steps = 0
        self._sequence = 0
        simulation_fps = 1.0 / args.dt
        self._sample_stride = max(1, round(simulation_fps / args.stream_fps))

    def start(self) -> None:
        self.thread.start()

    def enqueue(self, request: dict[str, Any]) -> str:
        request = dict(request)
        request["id"] = command_id(request.get("id"))
        with self._stop_lock:
            request["_stop_generation"] = self._stop_generation
        self.command_queue.put(request)
        return request["id"]

    def request_stop(self) -> int:
        with self._stop_lock:
            self._stop_generation += 1
        if self.scene is not None:
            self.scene.request_stop()
        cancelled = 0
        while True:
            try:
                queued = self.command_queue.get_nowait()
            except queue.Empty:
                break
            cancelled += 1
            self.broker.broadcast(
                {
                    "type": "result",
                    "id": queued.get("id"),
                    "status": "cancelled",
                    "error": "Cleared by stop request",
                }
            )
        return cancelled

    def shutdown(self) -> None:
        self.shutdown_event.set()
        self.request_stop()
        self.thread.join(timeout=5.0)

    def hello_message(self) -> dict[str, Any]:
        return {
            "type": "hello",
            "protocol_version": PROTOCOL_VERSION,
            "server": "aigc-pybullet-live",
            "scene": self.scene_manifest,
            "capabilities": [
                "text_command",
                "move_to",
                "move_delta",
                "place_at",
                "push_to",
                "rotate_to",
                "check_feasibility",
                "target_orientation",
                "multi_object_scene",
                "set_active_object",
                "reset_scene",
                "stop",
                "live_state",
            ],
            "stream_fps": self.args.stream_fps,
        }

    def get_latest_state(self) -> dict[str, Any] | None:
        with self._state_lock:
            return dict(self.latest_state) if self.latest_state else None

    def _run(self) -> None:
        try:
            import pybullet as p

            requested_delay = max(0.0, self.args.dt / self.args.speed)
            scene = CommandScene(
                p=p,
                env=SimulationEnv(gui=self.args.gui),
                robot_base=_parse_xyz(self.args.robot_base),
                object_path=Path(self.args.object).resolve() if self.args.object else None,
                object_scale=self.args.object_scale,
                object_mass=self.args.object_mass,
                object_friction=self.args.object_friction,
                scene_profile=self.args.scene_profile,
                object_position=_parse_xyz(self.args.object_position),
                scene_manifest_path=(
                    Path(self.args.scene_manifest).resolve() if self.args.scene_manifest else None
                ),
                step_delay=requested_delay if requested_delay >= 0.001 else 0.0,
                dt=self.args.dt,
            )
            self.scene = scene
            scene.target_steps = self.args.motion_steps
            scene.setup(PandaRobot)
            self.scene_manifest = describe_scene(scene)
            self.visual_shapes = self.scene_manifest["robot"]["visual_shapes"]
            scene.frame_observer = self._on_physics_step
            self._publish_state(force=True)
            self.ready_event.set()

            while not self.shutdown_event.is_set():
                try:
                    request = self.command_queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                self._execute_request(request)
        except Exception as exc:
            self.startup_error = f"{type(exc).__name__}: {exc}"
            self.ready_event.set()
            self.broker.broadcast({"type": "server_error", "error": self.startup_error})
        finally:
            if self.scene is not None:
                self.scene.close()

    def _execute_request(self, request: dict[str, Any]) -> None:
        assert self.scene is not None
        request_id = request["id"]
        with self._stop_lock:
            if request.get("_stop_generation") != self._stop_generation:
                self.broker.broadcast(
                    {
                        "type": "result",
                        "id": request_id,
                        "status": "cancelled",
                        "error": "Cancelled before execution",
                    }
                )
                return
            self.scene.clear_stop()
        label = request.get("text") or request.get("action") or "command"
        active = {"id": request_id, "label": str(label), "status": "running"}
        with self._active_lock:
            self._active_command = active
        self.broker.broadcast({"type": "result", "id": request_id, "status": "started"})
        self._publish_state(force=True)

        status = "completed"
        error = None
        self.scene.last_action_details = None
        try:
            succeeded = self._dispatch(request)
            if not succeeded:
                status = self.scene.last_command_status
                error = self.scene.last_error
        except CommandCancelled:
            self.scene.hold_position()
            status = "cancelled"
            error = "Command cancelled by user"
        except Exception as exc:
            self.scene.hold_position()
            status = "failed"
            error = str(exc)

        active["status"] = status
        self._publish_state(force=True)
        response = {"type": "result", "id": request_id, "status": status}
        if error:
            response["error"] = error
        if self.scene.last_action_details is not None:
            response["details"] = self.scene.last_action_details
        self.broker.broadcast(response)
        with self._active_lock:
            self._active_command = None

    def _dispatch(self, request: dict[str, Any]) -> bool:
        assert self.scene is not None
        if request["type"] == "command":
            text = request.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ProtocolError("Command requires non-empty 'text'")
            return bool(self.scene.execute(text, clear_stop=False))

        action = request.get("action")
        if action == "move_to":
            target = np.asarray(vector3(request.get("target")), dtype=float)
            self.scene._require_feasible("move_to", target)
            self.scene.move_to(target)
        elif action == "move_delta":
            self.scene.move_delta(np.asarray(vector3(request.get("delta"), "delta"), dtype=float))
        elif action == "place_at":
            target = np.asarray(vector3(request.get("target")), dtype=float)
            orientation = np.asarray(
                quaternion(request.get("orientation", [0.0, 0.0, 0.0, 1.0])),
                dtype=float,
            )
            self.scene.place(target, orientation)
        elif action == "push_to":
            self.scene.push_to(np.asarray(vector3(request.get("target")), dtype=float))
        elif action == "rotate_to":
            orientation = np.asarray(quaternion(request.get("orientation")), dtype=float)
            self.scene.rotate_object_to(orientation)
        elif action == "check_feasibility":
            operation = str(request.get("operation", "")).strip()
            if operation not in {"move_to", "place_at", "push_to", "rotate_to", "pick"}:
                raise ProtocolError("Unsupported feasibility operation")
            target = (
                np.asarray(vector3(request.get("target")), dtype=float)
                if operation not in {"pick", "rotate_to"}
                else None
            )
            orientation = (
                np.asarray(
                    quaternion(request.get("orientation", [0.0, 0.0, 0.0, 1.0])),
                    dtype=float,
                )
                if operation in {"place_at", "rotate_to"}
                else None
            )
            self.scene.last_action_details = self.scene.assess_action(
                operation,
                target,
                orientation,
            )
        elif action == "reset_scene":
            self.scene.reset_scene()
        elif action == "set_active_object":
            object_id = str(request.get("object_id", "")).strip()
            if not object_id:
                raise ProtocolError("set_active_object requires object_id")
            self.scene.set_active_object(object_id)
        elif action in {"pick", "lift", "release", "open", "close", "home"}:
            return bool(self.scene.execute(action, clear_stop=False))
        else:
            raise ProtocolError(f"Unsupported action: {action}")
        self.scene.last_command_status = "completed"
        self.scene.last_error = None
        return True

    def _on_physics_step(self, _scene) -> None:
        self._physics_steps += 1
        if self._physics_steps % self._sample_stride == 0:
            self._publish_state()

    def _publish_state(self, force: bool = False) -> None:
        if self.scene is None or not self.visual_shapes:
            return
        self._sequence += 1
        with self._active_lock:
            active = dict(self._active_command) if self._active_command else None
        state = capture_state(self.scene, self.visual_shapes, self._sequence, active)
        with self._state_lock:
            self.latest_state = state
        self.broker.broadcast(state)


class RobotRequestHandler(socketserver.StreamRequestHandler):
    def setup(self) -> None:
        super().setup()
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.session = ClientSession(self.connection)
        self.server.broker.add(self.session)

    def handle(self) -> None:
        simulator = self.server.simulator
        if not simulator.ready_event.wait(timeout=15.0) or simulator.startup_error:
            self.session.send(
                {"type": "server_error", "error": simulator.startup_error or "Simulator startup timed out"}
            )
            return
        self.session.send(simulator.hello_message())
        latest = simulator.get_latest_state()
        if latest:
            self.session.send(latest)

        while not self.session.closed:
            try:
                line = self.rfile.readline()
            except (ConnectionResetError, OSError):
                return
            if not line:
                return
            try:
                message = decode_message(line)
                self._route(message)
            except ProtocolError as exc:
                self.session.send({"type": "error", "error": str(exc)})

    def finish(self) -> None:
        self.server.broker.remove(self.session)
        try:
            super().finish()
        except OSError:
            pass

    def _route(self, message: dict[str, Any]) -> None:
        simulator = self.server.simulator
        message_type = message["type"]
        if message_type == "ping":
            self.session.send({"type": "pong", "server_time": time.time()})
        elif message_type in {"command", "action"}:
            if message_type == "command" and str(message.get("text", "")).strip().lower() in {
                "stop",
                "cancel",
                "停止",
                "中止",
                "取消",
            }:
                count = simulator.request_stop()
                request_id = command_id(message.get("id"))
                self.session.send({"type": "stop_ack", "id": request_id, "cleared_commands": count})
                self.session.send({"type": "result", "id": request_id, "status": "completed"})
                return
            request_id = simulator.enqueue(message)
            self.session.send({"type": "accepted", "id": request_id})
        elif message_type == "stop":
            count = simulator.request_stop()
            self.session.send({"type": "stop_ack", "cleared_commands": count})
        elif message_type == "get_state":
            state = simulator.get_latest_state()
            if state:
                self.session.send(state)
        else:
            raise ProtocolError(f"Unsupported message type: {message_type}")


class RobotTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, simulator, broker):
        self.simulator = simulator
        self.broker = broker
        super().__init__(address, RobotRequestHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Live PyBullet server for Blender interaction")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--object", default=None)
    parser.add_argument("--scene-manifest", default=None)
    parser.add_argument("--object-scale", type=float, default=0.05)
    parser.add_argument("--object-mass", type=float, default=0.5)
    parser.add_argument("--object-friction", type=float, default=0.9)
    parser.add_argument("--object-position", default="0.5,0,0.66")
    parser.add_argument("--scene-profile", choices=["tabletop", "floor"], default="tabletop")
    parser.add_argument("--robot-base", default="0,-0.35,0.626")
    parser.add_argument("--dt", type=float, default=1 / 240)
    parser.add_argument("--stream-fps", type=int, default=30)
    parser.add_argument("--motion-steps", type=int, default=80)
    parser.add_argument("--speed", type=float, default=1.0, help="Simulation playback speed multiplier")
    parser.add_argument("--gui", action="store_true", help="Also show the PyBullet debug window")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.dt <= 0 or args.stream_fps <= 0 or args.motion_steps <= 0 or args.speed <= 0:
        parser.error("dt, stream-fps, motion-steps, and speed must be positive")
    if args.object_scale <= 0 or args.object_mass <= 0 or args.object_friction < 0:
        parser.error("object-scale and object-mass must be positive; friction must be non-negative")

    broker = MessageBroker()
    simulator = LiveRobotSimulator(args, broker)
    simulator.start()
    if not simulator.ready_event.wait(timeout=30.0):
        raise RuntimeError("PyBullet simulator startup timed out")
    if simulator.startup_error:
        raise RuntimeError(simulator.startup_error)

    server = RobotTCPServer((args.host, args.port), simulator, broker)
    print(f"ROBOT_SERVER_READY {args.host}:{args.port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("Stopping robot server...", flush=True)
    finally:
        server.server_close()
        simulator.shutdown()
        broker.close()


if __name__ == "__main__":
    main()
