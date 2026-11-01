
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

            # Resume execution and monitor individual node updates.
            for update in graph.stream(
                None,
                config=config,
                stream_mode="updates",
            ):
                if "request_admin_approval" in update:
                    node_result = update["request_admin_approval"]

                    if node_result.get("admin_approval_status") == "PENDING":
                        print(
                            "\nBot: Your reservation request has been "
                            "sent to the administrator."
                        )
                        print(
                            "Waiting for the administrator's approval..."
                        )

                if "wait_admin_approval" in update:
                    node_result = update["wait_admin_approval"]
                    status = node_result.get("admin_approval_status")

                    if status == "APPROVED":
                        print("\nAdministrator approved your request.")

                    elif status == "REJECTED":
                        print("\nAdministrator rejected your request.")

                    elif status == "UNCLEAR":
                        print(
                            "\nAdministrator approval could not be confirmed."
                        )

            # Retrieve the latest graph state after execution.
            final_state = graph.get_state(config).values

            # Display the latest assistant response.
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

        except Exception:
            print("\nAn error occurred while processing your request.")
            print("Please try again.\n")


if __name__ == "__main__":
    main()
