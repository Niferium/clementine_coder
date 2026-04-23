"""
server.py — Flask web server with SSE streaming, file upload, and session management.

Endpoints:
    GET  /                  → Serve the chat UI (index.html)
    POST /chat              → Start a generation turn, returns session_id
    GET  /stream/<sid>      → SSE stream for an active generation
    POST /upload            → Accept a file upload, return temp path + metadata
    POST /reset/<sid>       → Clear session history
    GET  /status/<sid>      → Return current token count + active skill for a session

All terminal output goes through Logger. No print() calls in this module.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    stream_with_context,
)

from src.agent  import Agent
from src.logger import Logger


def create_app(agent: Agent, logger: Logger) -> Flask:
    """
    Create and configure the Flask app.

    Args:
        agent:  The shared Agent singleton.
        logger: The shared Logger singleton.

    Returns:
        Configured Flask application instance.
    """
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent.parent / "templates"),
    )
    app.secret_key = os.urandom(24)

    # ── Temp file store: {upload_id: {"path": str, "filename": str, "content": str}}
    _uploads: dict[str, dict] = {}

    # ── Active SSE queues: {session_id: queue.Queue}
    # (The agent owns the queues; we just drain them here)

    # ── Routes ────────────────────────────────────────────────────────────────

    @app.route("/")
    def index():
        """Serve the main chat UI."""
        return render_template("index.html")

    @app.route("/chat", methods=["POST"])
    def chat():
        """
        Start a generation turn.

        Expected JSON body:
            {
                "message":    "<user text>",
                "session_id": "<optional existing session id>",
                "upload_id":  "<optional upload id from /upload>"
            }

        Returns JSON:
            {"session_id": "<sid>"}

        The client should then open /stream/<sid> as an EventSource.
        """
        body       = request.get_json(force=True, silent=True) or {}
        message    = (body.get("message") or "").strip()
        session_id = body.get("session_id") or str(uuid.uuid4())
        upload_id  = body.get("upload_id")

        if not message:
            return jsonify({"error": "Empty message"}), 400

        # Resolve uploaded file if provided
        file_content: str | None = None
        filename:     str | None = None

        if upload_id and upload_id in _uploads:
            upload    = _uploads[upload_id]
            file_content = upload["content"]
            filename     = upload["filename"]

        # Kick off generation in background thread — returns a queue
        event_queue = agent.process(
            session_id   = session_id,
            user_message = message,
            file_content = file_content,
            filename     = filename,
        )

        # Store the queue so /stream can find it
        app.config.setdefault("_queues", {})[session_id] = event_queue

        logger.log_sse_event("chat_start", f"session={session_id[:8]} msg={message[:40]}")

        return jsonify({"session_id": session_id})

    @app.route("/stream/<session_id>")
    def stream(session_id: str):
        """
        SSE stream for an active generation.

        Drains the event queue for session_id and emits each event as
        a properly formatted SSE message. Ends when the sentinel None
        is received from the agent.

        SSE event format:
            event: <event_name>
            data: <json_payload>
            (blank line)

        Client usage:
            const es = new EventSource(`/stream/${sessionId}`);
            es.addEventListener('token', e => { ... });
        """
        queues = app.config.get("_queues", {})
        q      = queues.get(session_id)

        if q is None:
            return Response("No active stream for this session", status=404)

        @stream_with_context
        def generate_sse():
            """Drain the queue and yield SSE-formatted strings."""
            try:
                while True:
                    item = q.get()

                    # Sentinel — generation complete
                    if item is None:
                        yield "event: close\ndata: {}\n\n"
                        break

                    event     = item.get("event", "message")
                    data_dict = item.get("data", {})
                    data_json = json.dumps(data_dict)

                    logger.log_sse_event(event, str(data_dict)[:60])

                    yield f"event: {event}\ndata: {data_json}\n\n"

            except GeneratorExit:
                pass
            finally:
                # Clean up queue reference after stream ends
                queues.pop(session_id, None)

        return Response(
            generate_sse(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control":     "no-cache",
                "X-Accel-Buffering": "no",
                "Connection":        "keep-alive",
            },
        )

    @app.route("/upload", methods=["POST"])
    def upload():
        """
        Accept a file upload and store it temporarily.

        Reads the file content as text (UTF-8, fallback latin-1) and
        stores it in the in-memory _uploads dict indexed by a UUID.

        Returns JSON:
            {
                "upload_id": "<uid>",
                "filename":  "<original filename>",
                "lines":     <line count>
            }
        """
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400

        f        = request.files["file"]
        filename = f.filename or "uploaded_file"
        raw      = f.read()

        # Try UTF-8 first, fall back to latin-1
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            content = raw.decode("latin-1")

        upload_id = str(uuid.uuid4())
        _uploads[upload_id] = {
            "filename": filename,
            "content":  content,
        }

        lines = len(content.splitlines())
        logger.log_sse_event("upload", f"{filename} ({lines} lines)")

        return jsonify({
            "upload_id": upload_id,
            "filename":  filename,
            "lines":     lines,
        })

    @app.route("/reset/<session_id>", methods=["POST"])
    def reset(session_id: str):
        """
        Clear history for a session (new conversation).

        Returns JSON:
            {"ok": true}
        """
        agent.clear_session(session_id)
        logger.log_sse_event("reset", f"session={session_id[:8]}")
        return jsonify({"ok": True})

    @app.route("/status/<session_id>")
    def status(session_id: str):
        """
        Return current token count and active skill for a session.

        Returns JSON:
            {
                "token_count": int,
                "max_tokens":  int,
                "pct":         float,
                "skill":       str
            }
        """
        from src.agent import MAX_TOKENS

        session     = agent.get_session(session_id)
        token_count = agent.get_token_count(session_id)

        return jsonify({
            "token_count": token_count,
            "max_tokens":  MAX_TOKENS,
            "pct":         round(token_count / MAX_TOKENS * 100, 1),
            "skill":       session.get("skill", "general"),
        })

    return app
