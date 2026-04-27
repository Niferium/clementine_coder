from src.log.logger import Logger
import src.config as config
import gc
import signal
import sys  
import mlx.core as mx
import src.prompts.sys_prompt as sys_prompt
from mlx_lm import load, generate
from mlx_lm.sample_utils import make_sampler, make_logits_processors

class Main:
    def __init__(self):
        self.logger = Logger()
        self.mainModel = config.MAIN_MODEL
        self.routerModel = config.ROUTER_MODEL
        self.maxTokens = config.MAX_TOKENS

        self.routerTokens = config.ROUTER_TOKENS

        self._loaded_name:      str | None = None
        self._loaded_model                 = None

        self.sys_prompt = sys_prompt

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
           
    
    def chat(self):
        # Main generation function. It first ensures the main model is loaded, then generates a response based on the current conversation history and the new user input. It also handles token limits and logs the generation process.
        print(f"my max tokens{self.maxTokens}")
        model, tokenizer = self._refreshModel(self.mainModel)

        # Here you would implement the logic to prepare the input for generation, call the generate function, and handle the output.
        while True:
            user_input = input("User: ")
            if user_input.lower() == "exit":
                print("Exiting...")
                break
            
            # Prepare input for generation (this is where you would include conversation history, system prompts, etc.)
            systemPrompt = self.get_prompt_category(user_input)
            self.logger.log_debug(systemPrompt)
            if tokenizer.chat_template is not None:
                conversation = [
                    {"role": "system", "content": systemPrompt},
                    {"role": "user", "content": user_input}
                ]
                prompt = tokenizer.apply_chat_template(conversation, add_generation_prompt=True)
            else:
                prompt = self.sys_prompt.SYSTEM_PROMPT_SENIOR_SOFTWARE_ENGINEER() + "\n" + user_input
            input_tokens = tokenizer.encode(user_input)
            if len(input_tokens) > self.maxTokens:
                print(f"Input exceeds maximum token limit of {self.maxTokens}. Please shorten your input.")
                continue
            
            # Generate response
            sampler = make_sampler(temp=0.3, top_p=0.9)
            logits_processors = make_logits_processors(repetition_penalty=1.05)

            response = generate(
                model, 
                tokenizer, 
                prompt, 
                max_tokens=self.maxTokens, 
                verbose=True,
                sampler = sampler,
                logits_processors = logits_processors
            )
            self.logger.extract_and_log_code(response_text=response)
            

if __name__ == "__main__":
    main_agent = Main()
    signal.signal(signal.SIGINT, main_agent.signal_handler)
    main_agent.logger.log_debug_kirbo()
    main_agent.chat()