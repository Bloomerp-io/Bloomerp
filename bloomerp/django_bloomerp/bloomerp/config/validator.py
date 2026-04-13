from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
import inspect
from typing import Iterable, Type

from colorama import Fore, Style, init as colorama_init
from django.apps import apps
from django.conf import LazySettings, settings
from django.db.models import Model
from tenacity import retry_if_not_exception_message

from bloomerp.config.definition import BloomerpConfig
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.definition import BloomerpModelConfig
from bloomerp.modules.definition import module_registry

logger = logging.getLogger(__name__)
colorama_init(autoreset=True)


class ValidationType(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class ValidatorResponse:
    validation_type: ValidationType
    code: str
    message: str
    hint: str = ""
    subject: str = ""


@dataclass
class ValidationSectionResult:
    title: str
    description: str
    responses: list[ValidatorResponse] = field(default_factory=list)

    def has_errors(self) -> bool:
        return any(
            response.validation_type == ValidationType.ERROR
            for response in self.responses
        )

    def has_warnings(self) -> bool:
        return any(
            response.validation_type == ValidationType.WARNING
            for response in self.responses
        )


@dataclass
class ValidationResult:
    sections: list[ValidationSectionResult] = field(default_factory=list)

    def add_section(self, section: ValidationSectionResult) -> None:
        self.sections.append(section)

    def has_errors(self) -> bool:
        return any(
            section.has_errors()
            for section in self.sections
        )

    def has_warnings(self) -> bool:
        return any(
            section.has_warnings()
            for section in self.sections
        )

    def error_messages(self, styled: bool = False) -> list[str]:
        messages: list[str] = []
        for section in self.sections:
            error_responses = [
                response
                for response in section.responses
                if response.validation_type == ValidationType.ERROR
            ]
            if not error_responses:
                continue
            error_section = ValidationSectionResult(
                title=section.title,
                description=section.description,
                responses=error_responses,
            )
            messages.append(
                (
                    format_styled_validation_section(error_section)
                    if styled
                    else format_validation_section(error_section)
                )
            )
        return messages


class BloomerpConfigurationValidator:
    """Validate the bloomerp runtime configuration without producing side effects."""
    bloomerp_config_attr = "bloomerp_config"

    def __init__(
        self,
        settings: LazySettings,
        models: list[Type[Model]] | None = None,
    ) -> None:
        self.settings = settings
        self.models = models if models is not None else list(apps.get_models())

    @classmethod
    def from_runtime(cls) -> "BloomerpConfigurationValidator":
        return cls(settings=settings, models=list(apps.get_models()))

    def validate_settings(self) -> list[ValidatorResponse]:
        """Checks core Django and BloomERP settings."""
        responses: list[ValidatorResponse] = []

        if not getattr(self.settings, "BLOOMERP_CONFIG", None):
            responses.append(
                ValidatorResponse(
                    validation_type=ValidationType.ERROR,
                    code="settings.missing_bloomerp_config",
                    message="BLOOMERP_CONFIG setting is not set.",
                    hint=(
                        "Set BLOOMERP_CONFIG to a valid BloomerpConfig instance to customize "
                        "BloomERP behavior, or set it to None to silence this warning if default "
                        "behavior is fine."
                    ),
                    subject="BLOOMERP_CONFIG",
                )
            )
        else:
            bloomerp_config = self.settings.BLOOMERP_CONFIG
            if not isinstance(bloomerp_config, BloomerpConfig):
                responses.append(
                    ValidatorResponse(
                        validation_type=ValidationType.ERROR,
                        code="settings.invalid_bloomerp_config",
                        message="BLOOMERP_CONFIG setting is not an instance of BloomerpConfig.",
                        hint=(
                            "Ensure BLOOMERP_CONFIG is set to a valid BloomerpConfig instance, or set it to None for default behavior."
                        ),
                        subject="BLOOMERP_CONFIG",
                    )
                )
        
        return responses

    def validate_models(self) -> list[ValidatorResponse]:
        """Checks project model configuration and BloomERP inheritance rules."""
        responses: list[ValidatorResponse] = []

        for model_class in self.models:
            subject = f"model {model_class._meta.label}"

            if model_class._meta.abstract:
                continue
            
            app_module = model_class.__module__
            if app_module.startswith("django."):
                continue

            if model_class._meta.app_label == "bloomerp":
                continue
            
            if not issubclass(model_class, BloomerpModel):
                responses.append(
                    ValidatorResponse(
                        validation_type=ValidationType.WARNING,
                        code="models.not_bloomerp_model",
                        message=(
                            f"Model '{model_class._meta.label}' does not inherit from "
                            "BloomerpModel."
                        ),
                        hint=(
                            "This may be fine for third-party apps, but BloomERP models "
                            "should usually inherit from BloomerpModel."
                        ),
                        subject=subject,
                    )
                )

            # Check for bloomerp_config attribute and validate its type if present
            if not hasattr(model_class, self.bloomerp_config_attr):
                responses.append(
                    ValidatorResponse(
                        validation_type=ValidationType.WARNING,
                        code="models.missing_bloomerp_config",
                        message=(
                            f"Model '{model_class._meta.label}' does not have a "
                            "bloomerp_config attribute."
                        ),
                        hint=(
                            "Add a bloomerp_config attribute set to a BloomerpModelConfig "
                            "instance to customize behavior, or add an empty bloomerp_config "
                            "attribute to silence this warning if default behavior is fine."
                        ),
                        subject=subject,
                    )
                )
            else:
                config = getattr(model_class, self.bloomerp_config_attr)
                if not isinstance(config, BloomerpModelConfig):
                    responses.append(
                        ValidatorResponse(
                            validation_type=ValidationType.ERROR,
                            code="models.invalid_bloomerp_config",
                            message=(
                                f"Model '{model_class._meta.label}' has a bloomerp_config "
                                "attribute that is not an instance of BloomerpModelConfig. Please remove this attribute for " \
                                "default behavior, or set it to a valid BloomerpModelConfig instance."
                            ),
                            hint=(
                                "Ensure bloomerp_config is either removed or set to a valid BloomerpModelConfig instance."
                            ),
                            subject=subject,
                        )
                    )

        
        return responses

    def validate_modules(self) -> list[ValidatorResponse]:
        """Checks whether the BloomERP module registry contains loaded modules."""
        responses: list[ValidatorResponse] = []

        if not module_registry.get_all():
            responses.append(
                ValidatorResponse(
                    validation_type=ValidationType.WARNING,
                    code="modules.registry_empty",
                    message="The BloomERP module registry is empty.",
                    hint="Ensure module definitions are imported and module_registry.refresh() runs at startup.",
                    subject="module_registry",
                )
            )

        return responses

    def validate(self) -> ValidationResult:
        result = ValidationResult()

        for method_name, method in inspect.getmembers(self, predicate=callable):
            if method_name in {"validate", "validate_all"}:
                continue
            if not method_name.startswith("validate_"):
                continue

            description = inspect.getdoc(method) or "No validator description provided."
            title = method_name.replace("validate_", "").replace("_", " ").title()
            responses = list(method())
            result.add_section(
                ValidationSectionResult(
                    title=title,
                    description=description,
                    responses=responses,
                )
            )

        return result


def format_validation_message(response: ValidatorResponse) -> str:
    message = f"[{response.code}] {response.message}"
    if response.subject:
        message += f" | subject={response.subject}"
    if response.hint:
        message += f" | hint={response.hint}"
    return message


def format_styled_validation_message(response: ValidatorResponse) -> str:
    if response.validation_type == ValidationType.ERROR:
        color = Fore.RED
        label = "ERROR"
    elif response.validation_type == ValidationType.WARNING:
        color = Fore.YELLOW
        label = "WARNING"
    else:
        color = Fore.CYAN
        label = "INFO"

    lines = [
        f"{color}{Style.BRIGHT}BloomERP {label}{Style.RESET_ALL} [{response.code}]",
        f"  {response.message}",
    ]
    if response.subject:
        lines.append(f"  subject: {response.subject}")
    if response.hint:
        lines.append(f"  hint: {response.hint}")
    return "\n".join(lines)


def format_styled_validation_section(section: ValidationSectionResult) -> str:
    lines = [
        f"\n{Fore.BLUE}{Style.BRIGHT}{section.title}{Style.RESET_ALL}",
        f"{Style.DIM}{section.description}{Style.RESET_ALL}",
    ]

    if not section.responses:
        lines.append(f"{Fore.GREEN}{Style.BRIGHT}OKAY{Style.RESET_ALL}")
        return "\n".join(lines)

    if not section.has_errors() and not section.has_warnings():
        lines.append(f"{Fore.GREEN}{Style.BRIGHT}OKAY{Style.RESET_ALL}")
        return "\n".join(lines)

    for response in section.responses:
        lines.append(format_styled_validation_message(response))

    return "\n".join(lines)


def format_validation_section(section: ValidationSectionResult) -> str:
    lines = [section.title, section.description]

    if not section.responses:
        lines.append("OKAY")
        return "\n".join(lines)

    if not section.has_errors() and not section.has_warnings():
        lines.append("OKAY")
        return "\n".join(lines)

    for response in section.responses:
        lines.append(format_validation_message(response))

    return "\n".join(lines)


def log_validation_result(result: ValidationResult, *, include_errors: bool = True) -> None:
    for section in result.sections:
        if section.has_errors() and not include_errors:
            continue
        formatted = format_styled_validation_section(section)
        if section.has_errors():
            logger.error("\n%s", formatted)
        elif section.has_warnings():
            logger.warning("\n%s", formatted)
        else:
            logger.info("\n%s", formatted)


def validate_runtime_configuration(*, include_error_logs: bool = True) -> ValidationResult:
    result = BloomerpConfigurationValidator.from_runtime().validate()
    log_validation_result(result, include_errors=include_error_logs)
    return result
