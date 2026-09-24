from typing import BinaryIO
import asyncio
from functools import cache
from pathlib import Path

from pdfminer.high_level import extract_text as extract_pdf_text
import docx2txt
from langchain_core.documents.base import Document
from langchain_core.embeddings import Embeddings
from langchain_aws import BedrockEmbeddings

from transformers import AutoTokenizer

from app.config import get_settings


settings = get_settings()

async def extract_text_from_pdf(file: BinaryIO) -> Document:
    content = await asyncio.to_thread(extract_pdf_text, file)
    return Document(page_content=content)
 

async def extract_text_from_doc(file: BinaryIO):
    content = await asyncio.to_thread(docx2txt.process, file)
    return Document(page_content=content)

async def extract_text_from_txt(file: BinaryIO):
    def read_txt(file: BinaryIO):
        return file.read().decode()
    content = await asyncio.to_thread(read_txt, file)
    return Document(page_content=content)

@cache
def get_embedder() -> Embeddings:
    """
    Creates and returns a cached Embeddings instance.

    Returns:
        Embeddings: An instance of Langchain Embeddings.
    """
    if settings.EMBED_PROVIDER == "aws-bedrock":
        embedder = BedrockEmbeddings(
            model_id=settings.EMBED_MODEL,
            region_name=settings.AWS_REGION,
        )
        return embedder
    else:
        raise NotImplementedError(f"Embedding provider {settings.EMBED_PROVIDER} is not supported yet.")


@cache
def get_embedding_tokenizer():
    """
    Creates and returns a cached HF tokenizer for the embeddings

    Returns:
        Tokenizer: An instance of HF tokenizer
    """
    return AutoTokenizer.from_pretrained(settings.EMBED_TOKENIZER)


@cache
def get_prompt(name: str):
    current_dir = Path(__file__).parent
    prompt_path = current_dir / "prompts" / f"{name}_prompt.txt"
    with open(prompt_path, encoding="utf-8") as f:
        prompt = f.read()
    return prompt
