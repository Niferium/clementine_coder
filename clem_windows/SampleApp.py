# qwen_coder.py
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

MODEL_ID = "Qwen/Qwen2.5-Coder-1.5B"

print("Loading tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)

#Downloading model here
print("Loading model...")
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    torch_dtype=torch.float16,   # use float16 to fit in 8GB VRAM
    device_map="auto",           # auto places layers on GPU/CPU as needed
)
model.eval()

def chat(prompt: str, max_new_tokens: int = 512):
    messages = [
        {"role": "system", "content": "You are a helpful coding assistant."},
        {"role": "user",   "content": prompt},
    ]

    # Apply chat template
    text = tokenizer.apply_chat_template(+
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )

    inputs = tokenizer(text, return_tensors="pt").to(model.device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            temperature=0.7,
            top_p=0.95,
            do_sample=True,
            pad_token_id=tokenizer.eos_token_id,
        )

    # Decode only the new tokens (strip the prompt)
    new_tokens = outputs[0][inputs["input_ids"].shape[-1]:]
    return tokenizer.decode(new_tokens, skip_special_tokens=True)


# Example usage
print("Chatting with Qwen2.5-Coder...")
response = chat("Write a Python function to do binary search")
print(response)