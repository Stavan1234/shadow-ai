import ollama

print("Testing qwen2.5:14b...")
response = ollama.chat(
    model="qwen2.5:14b",
    messages=[
        {"role": "system", "content": "You are Shadow, a smart local AI assistant."},
        {"role": "user", "content": "Introduce yourself in 2 sentences."}
    ]
)
print("Shadow:", response["message"]["content"])