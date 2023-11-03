import os

from dotenv import load_dotenv

import pathway as pw
from pathway.stdlib.ml.index import KNNIndex
from llm_app.utils import deduplicate
from llm_app.model_wrappers import OpenAIChatGPTModel, OpenAIEmbeddingModel

from src.utils import send_discord_alerts

# Load environment variables
load_dotenv()

class DocumentInputSchema(pw.Schema):
    doc: str


class QueryInputSchema(pw.Schema):
    query: str
    user: str


# Helper Functions
@pw.udf
def build_prompt(documents, query):
    docs_str = "\n".join(documents)
    prompt = f"""Please process the documents below:
{docs_str}

Respond to query: '{query}'
"""
    return prompt


@pw.udf
def build_prompt_check_for_alert_request_and_extract_query(query: str) -> str:
    prompt = f"""Evaluate the user's query and identify if there is a request for notifications on answer alterations:
    User Query: '{query}'

    Respond with 'Yes' if there is a request for alerts, and 'No' if not,
    followed by the query without the alerting request part.

    Examples:
    "Tell me about windows in Pathway" => "No. Tell me about windows in Pathway"
    "Tell me and alert about windows in Pathway" => "Yes. Tell me about windows in Pathway"
    """
    return prompt


@pw.udf
def split_answer(answer: str) -> tuple[bool, str]:
    alert_enabled = "yes" in answer[:3].lower()
    true_query = answer[3:].strip(' ."')
    return alert_enabled, true_query


def build_prompt_compare_answers(new: str, old: str) -> str:
    prompt = f"""
    Are the two following responses deviating?
    Answer with Yes or No.

    First response: "{old}"

    Second response: "{new}"
    """
    return prompt


def make_query_id(user, query) -> str:
    return str(hash(query + user))  # + str(time.time())


@pw.udf
def construct_notification_message(query: str, response: str) -> str:
    return f'New response for question "{query}":\n{response}'


@pw.udf
def construct_message(response, alert_flag):
    if alert_flag:
        return response + "\n\n🔔 Activated"
    return response


def decision_to_bool(decision: str) -> bool:
    return "yes" in decision.lower()



def run(
    *,
    data_dir: str = os.environ.get("PATHWAY_DATA_DIR", "./data/events/"),
    api_key: str = os.environ.get("OPENAI_API_TOKEN", ""),
    host: str = "0.0.0.0",
    port: int = 8080,
    embedder_locator: str = "text-embedding-ada-002",
    embedding_dimension: int = 1536,
    model_locator: str = "gpt-3.5-turbo",
    max_tokens: int = 400,
    temperature: float = 0.0,
    discord_webhook_url: str = os.environ.get("DISCORD_WEBHOOK_URL", ""),
    **kwargs,
):
    # Part I: Build index
    embedder = OpenAIEmbeddingModel(api_key=api_key)

    documents = pw.io.jsonlines.read(
        data_dir,
        schema=DocumentInputSchema,
        mode="streaming",
        autocommit_duration_ms=50,
    )

    enriched_documents = documents + documents.select(
        data=embedder.apply(text=pw.this.doc, locator=embedder_locator)
    )

    index = KNNIndex(
        enriched_documents.data, enriched_documents, n_dimensions=embedding_dimension
    )

    # Part II: receive queries, detect intent and prepare cleaned query

    query, response_writer = pw.io.http.rest_connector(
        host=host,
        port=port,
        schema=QueryInputSchema,
        autocommit_duration_ms=50,
        keep_queries=True,
    )

    model = OpenAIChatGPTModel(api_key=api_key)

    query += query.select(
        prompt=build_prompt_check_for_alert_request_and_extract_query(query.query)
    )
    query += query.select(
        tupled=split_answer(
            model.apply(
                pw.this.prompt,
                locator=model_locator,
                temperature=0.3,
                max_tokens=100,
            )
        ),
    )
    query = query.select(
        pw.this.user,
        alert_enabled=pw.this.tupled[0],
        query=pw.this.tupled[1],
    )

    query += query.select(
        data=embedder.apply(text=pw.this.query, locator=embedder_locator),
        query_id=pw.apply(make_query_id, pw.this.user, pw.this.query),
    )

    # Part III: respond to queries

    query_context = query + index.get_nearest_items(query.data, k=3).select(
        documents_list=pw.this.doc
    ).with_universe_of(query)

    prompt = query_context.select(
        pw.this.query_id,
        pw.this.query,
        pw.this.alert_enabled,
        prompt=build_prompt(pw.this.documents_list, pw.this.query),
    )

    responses = prompt.select(
        pw.this.query_id,
        pw.this.query,
        pw.this.alert_enabled,
        response=model.apply(
            pw.this.prompt,
            locator=model_locator,
            temperature=temperature,
            max_tokens=max_tokens,
        ),
    )

    output = responses.select(
        result=construct_message(pw.this.response, pw.this.alert_enabled)
    )

    response_writer(output)

    # Part IV: send alerts about responses which changed significantly.

    responses = responses.filter(pw.this.alert_enabled)

    def acceptor(new: str, old: str) -> bool:
        if new == old:
            return False

        decision = model(
            build_prompt_compare_answers(new, old),
            locator=model_locator,
            max_tokens=20,
        )
        return decision_to_bool(decision)

    pw.io.jsonlines.write(responses, "./data/new_responses.jsonl")

    deduplicated_responses = deduplicate(
        responses,
        col=responses.response,
        acceptor=acceptor,
        instance=responses.query_id,
    )
    pw.io.jsonlines.write(
        deduplicated_responses, "./data/deduped_responses.jsonl"
    )

    alerts = deduplicated_responses.select(
        message=construct_notification_message(pw.this.query, pw.this.response)
    )
    
    send_discord_alerts(alerts.message, discord_webhook_url)

    pw.run()


if __name__ == "__main__":
    run()