import os
import re
import json
import uuid
from src.log.logger import Logger
import threading
from flask import Flask, request, jsonify, Response, stream_with_context, send_file, render_template
from flask_cors import CORS
import src.config as config
from src.model_agent import Agent
import os


#UI Chat version
class AppOld:
    
    def __init__(self):
        self.logger = Logger()
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
        self.mainModel = config.CODER_MODEL
        self._conversation_history = []
    
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
                    # def generate():
                    #     self._conversation_history.append(user_input[-1])
                        
                    #     full_response = ""
                    #     for chunk in self.agent.stream_chat(self._conversation_history, max_tokens=max_tokens):
                    #         full_response += chunk
                    #         yield f"data: {json.dumps({'delta': chunk})}\n\n"

                    #     # After streaming, extract code blocks and attach metadata
                    #     # blocks = self.extract_code_blocks(full_response)
                    #     # saved = []
                    #     # for b in blocks:
                    #     #     file_id = str(uuid.uuid4())[:8]
                    #     #     fname = f"code_{file_id}.{b['extension']}"
                    #     #     fpath = os.path.join(self.DOWNLOADS_DIR, fname)
                    #     #     with open(fpath, "w", encoding="utf-8") as f:
                    #     #         f.write(b["code"])
                    #     #     saved.append({
                    #     #         "file_id": fname,
                    #     #         "language": b["language"],
                    #     #         "extension": b["extension"],
                    #     #     })
                    #     self._conversation_history.append({"role": "assistant", "content": full_response})
                    #     yield f"data: {json.dumps({'done': True, 'files': []})}\n\n"
                    def generate():
                        MAX_RETRIES = 3
                        current_input = user_input  # user_input is list[dict] from outer scope
                        attempt = 0

                        while attempt < MAX_RETRIES:
                            full_response = ""

                            # ✅ LOG 1: confirm what's being sent each attempt
                            self.logger.log_debug(f"[RETRY] Attempt {attempt + 1} | messages count: {len(current_input)}")
                            self.logger.log_debug(f"[RETRY] Last user message: {current_input[-1]['content'][:300]}")

                            for chunk in self.agent.stream_chat(current_input, max_tokens=max_tokens):
                                full_response += chunk
                                yield f"data: {json.dumps({'delta': chunk})}\n\n"

                            # ✅ LOG 2: confirm what the model produced
                            self.logger.log_debug(f"[RETRY] Full response length: {len(full_response)}")
                            self.logger.log_debug(f"[RETRY] Full response preview: {full_response[:500]}")

                            result = self.agent.evaluate_last_response(full_response)

                            # ✅ LOG 3: confirm evaluation result
                            self.logger.log_debug(f"[RETRY] Evaluation result: {result}")

                            pass_fail = result.get("pass_fail", "fail")
                            score     = result.get("score", 0.0)

                            if pass_fail == "pass":
                                yield f"data: {json.dumps({'done': True, 'files': [], 'score': score, 'attempts': attempt + 1})}\n\n"
                                return

                            attempt += 1

                            if attempt >= MAX_RETRIES:
                                yield f"data: {json.dumps({'done': True, 'files': [], 'score': score, 'attempts': attempt, 'warning': 'Max retries reached'})}\n\n"
                                return

                            # Build corrective context from evaluation feedback
                            issues          = result.get("issues", [])
                            fixes           = result.get("fixes", [])

                            feedback_lines = []
                            if issues:
                                feedback_lines.append("Issues to fix:")
                                feedback_lines += [f"  - {i}" for i in issues]
                            if fixes:
                                feedback_lines.append("fixes:")
                                feedback_lines += [f"  - {r}" for r in fixes]

                            feedback_block = "\n".join(feedback_lines) if feedback_lines else "Please improve the overall quality and completeness of your response."

                            corrective_prompt = (
                                f"Your previous response scored {score:.2f}/1.0 and did not pass evaluation.\n\n"
                                f"{feedback_block}\n\n"
                                f"Please revise your response addressing all points above.\n\n"
                                f"Original request: {user_input[-1]['content']}"
                            )
                            print(f"Debug# Corrective Prompt {corrective_prompt}")

                            # Notify client a retry is in progress
                            yield f"data: {json.dumps({'retry': True, 'attempt': attempt, 'score': score})}\n\n"

                            # Re-prompt: keep history + inject corrective message as new user turn
                            # current_input = user_input + [{"role": "user", "content": corrective_prompt}]
                            current_input = user_input + [
                                {"role": "assistant", "content": full_response},  # previous attempt
                                {"role": "user", "content": corrective_prompt}    # feedback only
                            ]


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
            
        @self.app.route("/api/reset", methods=["POST"])
        def reset():
            self._conversation_history = []
            return jsonify({"status": "ok"})
        
    def run(self, host='0.0.0.0', port=5001, debug = True):
        self.app.run(host=host, port=port, debug=debug)



if __name__ == '__main__':
    app = AppOld()
    app.run(host='0.0.0.0', port=5001, debug=False)