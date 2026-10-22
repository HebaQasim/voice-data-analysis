"""Part 2 (step A): connect to Google Gemini through LangChain's ChatOpenAI.
The same setup as the coding assistant project: several models linked with fallbacks."""
import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()   # reads GEMINI_API_KEY from the .env file

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

MODELS = ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite"]


def create_model(name):
    return ChatOpenAI(
        model=name,
        api_key=os.getenv("GEMINI_API_KEY"),
        base_url=GEMINI_URL,
        reasoning_effort="low",
        timeout=30,
        max_retries=0,
    )


def create_llm(model_names):
    """Link the models with fallbacks: if a model fails or is busy, the next one in the list answers."""
    models = [create_model(name) for name in model_names]
    return models[0].with_fallbacks(models[1:])


# For writing SQL: the strongest model first, because a wrong query gives a wrong answer
llm = create_llm(MODELS)

# For short explanations of the results: a light model first,
# so the daily quota of the strong model is kept for writing SQL
fast_llm = create_llm(["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.5-flash"])


if __name__ == "__main__":
    response = llm.invoke("In one sentence, what is SQL?")
    print("Model:", response.response_metadata.get("model_name"))
    print(response.content)
