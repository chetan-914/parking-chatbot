
import uuid

from langchain_core.messages import AIMessage, HumanMessage

from app.graph import graph


def main():
    """Run the parking reservation chatbot in the terminal."""

    conversation_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    print("\n========================================")
    print("     PARKING SPACE RESERVATION BOT")
    print("========================================")
    print("Hello! I can help you check parking availability")
    print("and reserve or cancel a parking space.")
    print("Type 'exit' to close the chatbot.\n")

    # Initialize the graph. Execution pauses before human_input.
    graph.invoke(
        {
            "conversation_id": conversation_id,
        },
        config=config,
    )

    while True:
        try:
            user_text = input("You: ").strip()

            if not user_text:
                continue

            if user_text.lower() in {"exit", "quit"}:
                print("\nThank you for using the parking reservation bot!")
                break

            # Add the user's message to the graph state.
            graph.update_state(
                config,
                {
                    "messages": [
                        HumanMessage(content=user_text)
                    ]
                },
                as_node="human_input",
            )

            # Resume execution until the next human_input interrupt.
            final_state = None

            for state in graph.stream(
                None,
                config=config,
                stream_mode="values",
            ):
                final_state = state

            # Display only newly generated assistant messages.
            if final_state:
                messages = final_state.get("messages", [])

                assistant_messages = [
                    message
                    for message in messages
                    if isinstance(message, AIMessage)
                ]

                if assistant_messages:
                    print(
                        "\nBot:",
                        assistant_messages[-1].content,
                        "\n",
                    )

        except KeyboardInterrupt:
            print("\n\nChatbot stopped.")
            break

        except EOFError:
            print("\n\nChatbot stopped.")
            break

        except Exception as exc:
            print(f"\nAn error occurred: {exc}")
            print("Please try again.\n")


if __name__ == "__main__":
    main()
