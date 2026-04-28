
import src.config as config
from src.log.logger import Logger
import src.prompts.sys_prompt as sys_prompt
import gc
import signal
import sys
import threading
from typing import Iterator

import mlx.core as mx
from mlx_lm import load, generate, stream_generate
from mlx_lm.sample_utils import make_sampler, make_logits_processors


class Agent:
    
    def __init__(self):
        self.logger = Logger()
        self.mainModel = config.MAIN_MODEL
        self.routerModel = config.ROUTER_MODEL
        self.maxTokens = config.MAX_TOKENS
        self._lock = threading.Lock()

        self.routerTokens = config.ROUTER_TOKENS

        # ── Lazy model cache (one model in memory at a time) ─────────────────
        self._loaded_name:      str | None = None
        self._loaded_model                 = None
        self._loaded_tokenizer             = None
        self._loading = False
        self._error: str | None = None

        self.sys_prompt = sys_prompt

        # Auto-load default model on startup
        t = threading.Thread(target=self.load, args=(self.mainModel,), daemon=True)
        t.start()

    def load(self, model_name: str):
        with self._lock:
            self._loading = True
            self._error = None

        try:
            print(f"[model] Loading {model_name} …")
            model, tokenizer = load(model_name)
            with self._lock:
                self._loaded_model = model
                self._loaded_tokenizer = tokenizer
                self._loaded_name = model_name
                self._loading = False
            print(f"[model] {model_name} ready ✓")
        except Exception as e:
            with self._lock:
                self._loading = False
                self._error = str(e)
            print(f"[model] Load failed: {e}")

    def get_status(self) -> dict:
        with self._lock:
            if self._loading:
                return {"model_status": "loading", "model": self._loaded_name}
            if self._error:
                return {"model_status": "error", "error": self._error}
            if self._loaded_name is not None:
                return {"model_status": "ready", "model": self._loaded_name}
            return {"model_status": "not_loaded"}
    
    def get_prompt_category(self, user_prompt) -> str:
        # returns the appropriate prompt based on user prompt
        """
            Returns the appropriate engineering category based on the content of user_text.

            Args:
                user_text (str): The text to analyze for engineering categories
        
            Returns:
                str: "sys_engineer" if "use engineer" is found, 
                    "use python" if "use python" is found, 
                    "general prompt" otherwise
        """
        import re

        if bool(re.search(r'use engineer', user_prompt, re.IGNORECASE)):
            self.logger.log_debug(f"Agent will use Engineer")
            return self.sys_prompt.SYSTEM_PROMPT_SENIOR_SOFTWARE_ENGINEER()
        
        elif bool(re.search(r'use python', user_prompt, re.IGNORECASE)):
            self.logger.log_debug(f"Agent will use Python")
            return self.sys_prompt.SYSTEM_PROMPT_PYTHON()
        
        elif bool(re.search(r'use cim', user_prompt, re.IGNORECASE)):
            self.logger.log_debug(f"Agent will use Chat Maker for LLMS")
            return self.sys_prompt.SYSTEM_PROMPT_CHAT_INTERFACE_MAKER()
        else:
            self.logger.log_debug(f"Agent will use default")
            return self.sys_prompt.SYSTEM_PROMPT_SENIOR_SOFTWARE_ENGINEER()
        
    # starts the model and make it running
    def startup(self):
        """
        Preload the model LLM and pass the parameters
        """
        self.logger.log_header()
        self.logger.log_debug_kirbo()
        self.logger.log_startup(self.mainModel, self.routerModel, self.maxTokens)

        self.logger.log_model_ready(self.mainModel)

        return self._loaded_model, self._loaded_tokenizer

    def chat(self, user_input: list[dict], max_tokens: int = 2048) -> str:

        # Prepare input for generation (this is where you would include conversation history, system prompts, etc.)
        rawUserInput = user_input[-1]["content"]
        systemPrompt = self.get_prompt_category(rawUserInput)
        self.logger.log_debug(systemPrompt)
        if self._loaded_tokenizer.chat_template is not None:
            conversation = [
                {"role": "system", "content": systemPrompt},
                {"role": "user", "content": rawUserInput}
            ]
            prompt = self._loaded_tokenizer.apply_chat_template(conversation, add_generation_prompt=True)
        else:
            prompt = self.sys_prompt.SYSTEM_PROMPT_SENIOR_SOFTWARE_ENGINEER() + "\n" + rawUserInput
            input_tokens = self._loaded_tokenizer.encode(rawUserInput)

        if len(input_tokens) > self.maxTokens:
            print(f"Input exceeds maximum token limit of {self.maxTokens}. Please shorten your input.")
            
        #Settings for llm
        sampler = make_sampler(temp=0.3, top_p=0.9)
        logits_processors = make_logits_processors(repetition_penalty=1.05)

        response = generate(
            self._loaded_model, 
            self._loaded_tokenizer, 
            prompt, 
            max_tokens=self.maxTokens, 
            verbose=True,
            sampler = sampler,
            logits_processors = logits_processors
        )
        return response

    def stream_chat(self, user_input: list[dict], max_tokens: int = 2048) -> Iterator[str]:

        # Prepare input for generation (this is where you would include conversation history, system prompts, etc.)
        rawUserInput = user_input[-1]["content"]
        systemPrompt = self.get_prompt_category(rawUserInput)

        print(f"my prompt {systemPrompt} raw print {rawUserInput}")
        self.logger.log_debug(systemPrompt)
        if self._loaded_tokenizer.chat_template is not None:
            conversation = [
                {"role": "system", "content": systemPrompt},
                {"role": "user", "content": rawUserInput}
            ]
            prompt = self._loaded_tokenizer.apply_chat_template(conversation, add_generation_prompt=True)
        else:
            prompt = self.sys_prompt.SYSTEM_PROMPT_SENIOR_SOFTWARE_ENGINEER() + "\n" + rawUserInput
        
        input_tokens = self._loaded_tokenizer.encode(rawUserInput)
        if len(input_tokens) > self.maxTokens:
            print(f"Input exceeds maximum token limit of {self.maxTokens}. Please shorten your input.")

        with self._lock:
            model, tokenizer = self._loaded_model, self._loaded_tokenizer
        
        #Settings for llm
        sampler = make_sampler(temp=0.3, top_p=0.9)
        logits_processors = make_logits_processors(repetition_penalty=1.05)

        for chunk in stream_generate(
            model,
            tokenizer,
            prompt=prompt,
            max_tokens=self.maxTokens,
            sampler = sampler,
            logits_processors = logits_processors
        ):
            # mlx_lm ≥ 0.16 yields GenerationResponse objects; older yields str
            if hasattr(chunk, "text"):
                yield chunk.text
            else:
                yield chunk