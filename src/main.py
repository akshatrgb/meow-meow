from src.ai.openrouter_client import chat


def main():
    print("\n🐱 Meow Meow is awake!")
    print("Type 'exit' to say goodbye.\n")

    history = []

    while True:
        message = input("You: ").strip()

        if message.lower() in ["exit", "quit"]:
            print("\nMeow Meow: Byeee! Meow meow! ❤️")
            break

        if not message:
            continue

        try:
            reply = chat(message, history)

            print(f"\nMeow Meow: {reply}\n")

            history.extend([
                {"role": "user", "content": message},
                {"role": "assistant", "content": reply}
            ])

        except Exception as error:
            print(f"\nOops! Something went wrong: {error}\n")


if __name__ == "__main__":
    main()
