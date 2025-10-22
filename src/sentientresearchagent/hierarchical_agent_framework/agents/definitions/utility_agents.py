from agno.agent import Agent as AgnoAgent
from agno.models.litellm import LiteLLM
from loguru import logger
import os

LLM_MODEL_ID_SUMMARIZER = os.getenv("LITELLM_MODEL_ID", "fireworks_ai/accounts/fireworks/models/llama-v3-70b-instruct")

SUMMARIZER_SYSTEM_MESSAGE = """You are an expert summarization assistant. Your task is to summarize the provided text content that you will receive.
The summary should be comprehensive and between 500-700 words.
It should capture the most critical information relevant for an AI agent that will use this summary for planning its next steps.
Focus on key outcomes, decisions, facts, and figures. Include important details while avoiding conversational fluff.
Output only the summarized text. Do NOT include any preambles, apologies, or other self-references like 'Here is the summary:'. Just the summary text itself.
"""

try:
    context_summarizer_agno_agent = AgnoAgent(
        model=LiteLLM(id=LLM_MODEL_ID_SUMMARIZER),
        system_message=SUMMARIZER_SYSTEM_MESSAGE,
        name="ContextSummarizer_Agno"
    )
    logger.info(f"Successfully initialized ContextSummarizer_Agno with model {LLM_MODEL_ID_SUMMARIZER}")
except Exception as e:
    logger.error(f"Failed to initialize ContextSummarizer_Agno: {e}")
    context_summarizer_agno_agent = None

if context_summarizer_agno_agent is None:
    logger.warning("ContextSummarizer_Agno agent could not be initialized. Summarization will fall back to truncation.")