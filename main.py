from old.logger import Logger
import config
import gc
import signal
import sys  
import mlx.core as mx
from mlx_lm import load, generate

class Main:
    def __init__(self):
        self.logger = Logger()
        self.mainModel = config.MAIN_MODEL
        self.routerModel = config.ROUTER_MODEL
        self.maxTokens = config.MAX_TOKENS

        self.routerTokens = config.ROUTER_TOKENS

        self._loaded_name:      str | None = None
        self._loaded_model                 = None

    def _refreshModel(self, model_name: str):
        # Loads the specified model, unloading any previously loaded model to free up memory. If the requested model is already loaded, it simply returns it.

        if self._loaded_name == model_name:
            return self._loaded_model, self._loaded_tokenizer

        if self._loaded_model is not None:
            print(f"   🔄 Unloading {self._loaded_name}...")
            self._loaded_model     = None
            self._loaded_tokenizer = None
            self._loaded_name      = None
            gc.collect()
            mx.metal.clear_cache()

        print(f"   📦 Loading {model_name}...")
        self._loaded_model, self._loaded_tokenizer = load(model_name)
        self._loaded_name = model_name
        return self._loaded_model, self._loaded_tokenizer
    
    def signal_handler(self, sig, frame):
        print('Session Ended')
        sys.exit(0)

    
    def chat(self):
        # Prompts
        SYSTEM_PROMPT = """You are a helpful and precise assistant for code generation tasks."""
    
        # Main generation function. It first ensures the main model is loaded, then generates a response based on the current conversation history and the new user input. It also handles token limits and logs the generation process.

        model, tokenizer = self._refreshModel(self.mainModel)

        # Here you would implement the logic to prepare the input for generation, call the generate function, and handle the output.
        while True:
            user_input = input("User: ")
            if user_input.lower() == "exit":
                print("Exiting...")
                break
            
            # Prepare input for generation (this is where you would include conversation history, system prompts, etc.)
            if tokenizer.chat_template is not None:
                conversation = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_input}
                ]
                prompt = tokenizer.apply_chat_template(conversation, add_generation_prompt=True)
            else:
                prompt = SYSTEM_PROMPT + "\n" + user_input
            input_tokens = tokenizer.encode(user_input)
            if len(input_tokens) > self.maxTokens:
                print(f"Input exceeds maximum token limit of {self.maxTokens}. Please shorten your input.")
                continue
            
            # Generate response
            response = generate(model, tokenizer, prompt, self.maxTokens)
            print(f"Response: {response}")

if __name__ == "__main__":
    main_agent = Main()
    signal.signal(signal.SIGINT, main_agent.signal_handler)
    main_agent.logger.log_debug_kirbo()
    main_agent.chat()