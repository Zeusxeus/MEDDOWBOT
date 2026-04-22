
with open("handlers/reddit.py", "r") as f:
    content = f.read()

# Fix types in callback.message
content = content.replace(
    "await callback.message.edit_text",
    "if isinstance(callback.message, types.Message):\n        await callback.message.edit_text"
)
content = content.replace(
    "await callback.message.reply",
    "if isinstance(callback.message, types.Message):\n            await callback.message.reply"
)
# Special case for "if isinstance" nesting
content = content.replace(
    "if isinstance(callback.message, types.Message):\n        if isinstance(callback.message, types.Message):\n",
    "if isinstance(callback.message, types.Message):\n"
)

# And fix chat.id
content = content.replace(
    "chat_id=callback.message.chat.id,",
    "chat_id=callback.message.chat.id if isinstance(callback.message, types.Message) else 0,"
)

with open("handlers/reddit.py", "w") as f:
    f.write(content)
