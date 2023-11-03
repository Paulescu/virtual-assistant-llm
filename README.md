# Build a virtual assistant using real-time LLMs

## Context

Building a Virtual Assistant using LLMs takes a bit more work than just sending API calls to OpenAI.

[CHART]


## Run the whole thing in 5 minutes

1. Install all project dependencies inside an isolated virtual env, using Python Poetry
    ```
    $ make init
    ```

2. Create an `.env` file and fill in the necessary credentials. You will need an OpenAI API Key, and a Discord Webhook to receive notifications.
    ```
    $ cp .env.example .env
    ```

3. Run the virtual assistant
    ```
    $ make run
    ```

4. Send the first request
    ```
    $ make request
    ```

5. Simulate push of first event to the data warehouse
    ```
    $ make push_first_event
    ```

6. Simualte push of the second event to the data warehouse
    ```
    $ make push_second_event
    ```

## Video lecture

[TODO]

## Wanna learn more real-time LLMOps?

Join more than 10k subscribers to the Real-World ML Newsletter. Every Saturday morning.