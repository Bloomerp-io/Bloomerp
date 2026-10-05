from __future__ import annotations

import json
from collections.abc import Callable

from babel.messages.catalog import Catalog, Message
from pydantic import BaseModel, Field

from bloomerp.config.definition import BloomerpI18nLLMSettings
from bloomerp.i18n.catalogs import source_values, translated_values, validate_message


class TranslationResult(BaseModel):
    index: int
    translations: list[str]


class TranslationBatch(BaseModel):
    results: list[TranslationResult] = Field(default_factory=list)


def create_langchain_model(settings: BloomerpI18nLLMSettings) -> object:
    """Create a translator model, using its default temperature unless overridden."""
    try:
        from langchain.chat_models import init_chat_model
    except ImportError as exc:
        raise RuntimeError(
            "Machine translation requires LangChain. Install Bloomerp with the "
            "'i18n-llm' extra and install the LangChain integration for your provider."
        ) from exc

    kwargs: dict[str, object] = {}
    if settings.temperature is not None:
        kwargs["temperature"] = settings.temperature
    if settings.provider:
        kwargs["model_provider"] = settings.provider
    return init_chat_model(settings.model, **kwargs)


def _needs_translation(message: Message, include_fuzzy: bool) -> bool:
    values = translated_values(message)
    return not all(values) or (include_fuzzy and "fuzzy" in message.flags)


def translate_catalog(
    catalog: Catalog,
    target_language: str,
    source_language: str,
    settings: BloomerpI18nLLMSettings,
    *,
    include_fuzzy: bool = False,
    mark_fuzzy: bool = True,
    model_factory: Callable[[BloomerpI18nLLMSettings], object] = create_langchain_model,
) -> int:
    candidates = [
        message
        for message in catalog
        if message.id and _needs_translation(message, include_fuzzy)
    ]
    if not candidates:
        return 0

    model = model_factory(settings)
    structured_model = model.with_structured_output(TranslationBatch)
    translated = 0

    for start in range(0, len(candidates), settings.batch_size):
        messages = candidates[start : start + settings.batch_size]
        payload = [
            {
                "index": index,
                "source": source_values(message),
                "target_plural_forms": (
                    catalog.num_plurals if isinstance(message.id, tuple) else 1
                ),
                "context": message.context,
                "locations": [location[0] for location in message.locations[:3]],
            }
            for index, message in enumerate(messages)
        ]
        response = structured_model.invoke(
            [
                (
                    "system",
                    "You translate concise business-software interface text. Preserve all "
                    "placeholders, HTML tags, URLs, whitespace and line breaks exactly. "
                    "Return exactly target_plural_forms translated strings for each message. "
                    "For languages with more than two plural forms, derive every required form "
                    "from the supplied singular and plural source text.",
                ),
                (
                    "human",
                    f"Translate from {source_language} to {target_language}. "
                    f"Messages:\n{json.dumps(payload, ensure_ascii=False)}",
                ),
            ]
        )
        if isinstance(response, dict):
            response = TranslationBatch.model_validate(response)
        result_by_index = {result.index: result for result in response.results}

        for index, message in enumerate(messages):
            result = result_by_index.get(index)
            expected = catalog.num_plurals if isinstance(message.id, tuple) else 1
            if result is None or len(result.translations) != expected:
                raise RuntimeError(f"Translator returned invalid plural forms for {message.id!r}.")
            previous = message.string
            message.string = (
                tuple(result.translations)
                if isinstance(message.id, tuple)
                else result.translations[0]
            )
            errors = validate_message(message)
            if errors:
                message.string = previous
                raise RuntimeError(f"Invalid translation for {message.id!r}: {', '.join(errors)}")
            if mark_fuzzy:
                message.flags.add("fuzzy")
            else:
                message.flags.discard("fuzzy")
            translated += 1

    return translated
