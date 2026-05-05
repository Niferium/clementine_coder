import os
import re
import json
import uuid
import threading
from flask import Flask, request, jsonify, Response, stream_with_context, send_file, render_template
from flask_cors import CORS
import src.config as config
from src.model_agent import Agent
import os


#UI Chat version
class App:
    
    def __init__(self):
        self.BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        self.app = Flask(
            __name__,
            template_folder=os.path.join(self.BASE_DIR, "src/ui/templates"),
            static_folder=os.path.join(self.BASE_DIR, "src/ui/static"),
            static_url_path='/static'
        )
        self.agent = Agent()
        self.maxTokens = config.MAX_TOKENS
        self.EXT_MAP = {
            "python": "py", "py": "py",
            "javascript": "js", "js": "js",
            "typescript": "ts", "ts": "ts",
            "html": "html", "htm": "html",
            "css": "css",
            "kotlin": "kt", "kt": "kt",
            "java": "java",
            "swift": "swift",
            "rust": "rs",
            "go": "go",
            "c": "c",
            "cpp": "cpp", "c++": "cpp",
            "csharp": "cs", "c#": "cs",
            "ruby": "rb",
            "php": "php",
            "shell": "sh", "bash": "sh", "sh": "sh",
            "sql": "sql",
            "r": "r",
            "dart": "dart",
            "scala": "scala",
            "xml": "xml",
            "json": "json",
            "yaml": "yaml", "yml": "yaml",
            "toml": "toml",
            "markdown": "md", "md": "md",
            "dockerfile": "dockerfile",
            "makefile": "makefile",
            "vue": "vue",
            "svelte": "svelte",
            "jsx": "jsx",
            "tsx": "tsx",
            "lua": "lua",
            "perl": "pl",
            "haskell": "hs",
            "elixir": "ex",
            "erlang": "erl",
            "clojure": "clj",
            "groovy": "groovy",
            "objc": "m", "objective-c": "m",
            "assembly": "asm", "asm": "asm",
            "graphql": "graphql",
            "protobuf": "proto",
        }
        
        self._setup_routes()
        self.mainModel = config.MAIN_MODEL
    
    def extract_code_blocks(self, text):
        """Extract all fenced code blocks with their language tags."""
        pattern = r"```(\w+)?\n([\s\S]*?)```"
        blocks = []
        for match in re.finditer(pattern, text):
            lang = (match.group(1) or "txt").lower().strip()
            code = match.group(2).rstrip()
            ext = self.EXT_MAP.get(lang, lang if lang else "txt")
            blocks.append({"language": lang, "extension": ext, "code": code})
        return blocks
    
    def _setup_routes(self):
        @self.app.route('/')
        def index():
            return render_template("index.html")
        
        @self.app.route("/api/health", methods=["GET"])
        def health():
            status = self.agent.get_status()
            return jsonify({"status": "ok", **status})
        
        @self.app.route("/api/load-model", methods=["POST"])
        def load_model():
            data = request.get_json(force=True)
            model_name = data.get("model", self.mainModel)

            def do_load():
                self.agent.load(model_name)

            t = threading.Thread(target=do_load, daemon=True)
            t.start()
            return jsonify({"status": "loading", "model": model_name})

        
        @self.app.route('/api/chat', methods=['POST'])
        def chat():
            data = request.get_json(force=True)
            user_input = data.get("messages", [])
            stream = data.get("stream", True)
            max_tokens = data.get("max_tokens", self.maxTokens)

            if not user_input:
                return jsonify({"error": "messages required"}), 400
            
            """Chat endpoint for LLM interaction"""
            try:
                if stream:
                    def generate():
                        full_response = ""
                        for chunk in self.agent.stream_chat(user_input, max_tokens=max_tokens):
                            full_response += chunk
                            yield f"data: {json.dumps({'delta': chunk})}\n\n"

                        # After streaming, extract code blocks and attach metadata
                        # blocks = self.extract_code_blocks(full_response)
                        # saved = []
                        # for b in blocks:
                        #     file_id = str(uuid.uuid4())[:8]
                        #     fname = f"code_{file_id}.{b['extension']}"
                        #     fpath = os.path.join(self.DOWNLOADS_DIR, fname)
                        #     with open(fpath, "w", encoding="utf-8") as f:
                        #         f.write(b["code"])
                        #     saved.append({
                        #         "file_id": fname,
                        #         "language": b["language"],
                        #         "extension": b["extension"],
                        #     })

                        yield f"data: {json.dumps({'done': True, 'files': []})}\n\n"

                    return Response(
                        stream_with_context(generate()),
                        mimetype="text/event-stream",
                        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
                    )
                else:
                    response_text = self.agent.chat(user_input, max_tokens=max_tokens)
                    # blocks = self.extract_code_blocks(response_text)
                    # saved = []
                    # for b in blocks:
                    #     file_id = str(uuid.uuid4())[:8]
                    #     fname = f"code_{file_id}.{b['extension']}"
                    #     fpath = os.path.join(self.DOWNLOADS_DIR, fname)
                    #     with open(fpath, "w", encoding="utf-8") as f:
                    #         f.write(b["code"])
                    #     saved.append({
                    #         "file_id": fname,
                    #         "language": b["language"],
                    #         "extension": b["extension"],
                    #     })
                    return jsonify({"response": response_text, "files": []})
            except Exception as e:
                return jsonify({
                    "error": str(e),
                    "status": "error"
                }), 500
            
    def run(self, host='0.0.0.0', port=5001, debug = True):
        self.app.run(host=host, port=port, debug=debug)



if __name__ == '__main__':
    app = App()
    app.run(host='0.0.0.0', port=5001, debug=False)