from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Literal, TypeVar

from django.core.exceptions import FieldDoesNotExist
from django.db import models, transaction
from django.db.models import Model
from django.test import TestCase

from bloomerp.models.definition import BloomerpModelConfig, get_model_config
from bloomerp.services.sql_services import SqlExecutor
from bloomerp.workspaces.analytics_tile.model import AnalyticsTileConfig, AnalyticsTileType
from bloomerp.workspaces.base import BaseTileConfig
from bloomerp.workspaces.registry import TILE_TYPE_REGISTRY


ModelType = TypeVar("ModelType", bound=Model)


@dataclass(frozen=True)
class ExpectedModelException:
    """An exception expected during one model lifecycle operation."""

    phase: Literal["create", "update", "delete"]
    exception: type[Exception] | tuple[type[Exception], ...]
    message_regex: str | None = None


@dataclass
class ModelScenario(Generic[ModelType]):
    """Declarative lifecycle expectations for a model.

    ``create_args`` always defines the create phase. Non-``None`` ``update_args``
    defines the update phase. Non-empty ``delete_validators`` or an expected
    delete exception defines the delete phase. ``post_create`` receives the
    refreshed instance before create validators run.
    """

    name: str
    description: str | None = None
    preparation: Callable[[], None] | None = None
    post_create: Callable[[ModelType], None] | None = None
    create_args: dict[str, Any] | Callable[[], dict[str, Any]] = field(
        default_factory=dict
    )
    create_validators: Callable[[ModelType], bool] | list[
        Callable[[ModelType], bool]
    ] = field(default_factory=list)
    update_args: dict[str, Any] | Callable[[], dict[str, Any]] | None = None
    update_validators: Callable[[ModelType], bool] | list[
        Callable[[ModelType], bool]
    ] = field(default_factory=list)
    delete_validators: Callable[[ModelType], bool] | list[
        Callable[[ModelType], bool]
    ] = field(default_factory=list)
    expected_exceptions: list[ExpectedModelException] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Reject update expectations when the scenario has no update operation."""
        update_exception = any(
            expected.phase == "update" for expected in self.expected_exceptions
        )
        if self.update_args is None and (self.update_validators or update_exception):
            raise ValueError(
                "update_args must be provided when update expectations are configured"
            )

        phases = [expected.phase for expected in self.expected_exceptions]
        if len(phases) != len(set(phases)):
            raise ValueError("expected_exceptions may contain only one entry per phase")

        delete_exception = "delete" in phases
        if self.delete_validators and delete_exception:
            raise ValueError(
                "delete_validators cannot be configured when deletion is expected to fail"
            )


class BloomerpModelTestCase(TestCase):
    """Base class providing common configuration checks for a model."""

    model: type[models.Model] | None = None

    def get_model_config(self) -> BloomerpModelConfig | None:
        """Return the configured model's Bloomerp metadata."""
        if self.model is None:
            return None
        return get_model_config(self.model)

    def test_model_config_is_valid(self) -> None:
        """
        Use case: A model declares Bloomerp configuration.
        Expected result: The configuration can be validated from its serialized form.
        """
        # 1. Do not execute the reusable base class itself.
        config = self.get_model_config()
        if config is None:
            return

        # 2. Revalidate the complete configuration instead of trusting import-time state.
        validated = BloomerpModelConfig.model_validate(config.__dict__)
        self.assertIsInstance(validated, BloomerpModelConfig)

        # 3. Validate configured layout, search, and dataview field references.
        for field_name, source in self.get_configured_field_references(config):
            with self.subTest(field_name=field_name, source=source):
                self.assert_model_has_field(field_name, source=source)

    def test_model_tiles_are_valid(self) -> None:
        """
        Use case: A model declares reusable workspace tiles.
        Expected result: Every tile is registered and valid; analytics SQL executes.
        """
        # 1. Load every tile from the model configuration.
        config = self.get_model_config()
        if config is None:
            return

        # 2. Validate each tile independently for useful failure reporting.
        for tile in config.tiles:
            with self.subTest(tile_id=tile.id, tile_type=type(tile).__name__):
                self.validate_tile(tile)

    def validate_tile(self, tile: BaseTileConfig) -> None:
        """Validate one tile, including executing analytics SQL."""
        validated = type(tile).model_validate(tile.model_dump())
        self.assertIsInstance(validated, type(tile))
        TILE_TYPE_REGISTRY.key_for_config(tile)

        if not isinstance(tile, AnalyticsTileConfig):
            return

        AnalyticsTileType.from_key(tile.type)
        response = SqlExecutor().execute_query(tile.query, paginate=False)
        output_columns = set(response.columns)

        configured_fields = {
            field.name for fields in tile.fields.values() for field in fields
        }
        self.assertFalse(
            configured_fields - output_columns,
            "Analytics tile fields are missing from its SQL output: "
            f"{sorted(configured_fields - output_columns)}",
        )

        non_variable_filters = {
            filter_config.field
            for filter_config in tile.filters
            if not filter_config.is_variable
        }
        self.assertFalse(
            non_variable_filters - output_columns,
            "Analytics tile filters are missing from its SQL output: "
            f"{sorted(non_variable_filters - output_columns)}",
        )

    def get_configured_field_references(
        self, config: BloomerpModelConfig
    ) -> list[tuple[str, str]]:
        """Collect model-field references from declarative model configuration."""
        references: list[tuple[str, str]] = []

        detail_settings = config.detail_view_settings
        if detail_settings:
            for layout in detail_settings.layouts:
                for row in layout.rows:
                    for item in row.items:
                        if isinstance(item.id, str):
                            references.append((item.id, f"layout {layout.name!r}"))

        search_fields = config.string_search_settings.string_search_fields or []
        references.extend((field_name, "string search") for field_name in search_fields)

        model_view_settings = config.model_view_settings
        if model_view_settings:
            for dataview in model_view_settings.default_dataviews:
                dataview_name = f"dataview {dataview.name!r}"
                references.extend(
                    (field_name, dataview_name)
                    for field_name in dataview.display_fields
                )
                references.extend(
                    (field_name.split("__", 1)[0], dataview_name)
                    for field_name in dataview.default_filters
                )
                for attribute in (
                    "sort_field",
                    "group_by_field",
                    "start_field",
                    "end_field",
                    "color_grouping_field",
                    "dependency_from_field",
                    "dependency_for_field",
                ):
                    field_name = getattr(dataview, attribute, None)
                    if field_name:
                        references.append((field_name, dataview_name))
                for attribute in ("row_fields", "column_fields", "value_fields"):
                    references.extend(
                        (field_name, dataview_name)
                        for field_name in getattr(dataview, attribute, [])
                    )

        return references

    def assert_model_has_field(self, field_path: str, *, source: str) -> None:
        """Assert that a Django field path or model property can be resolved."""
        if self.model is None:
            raise AssertionError("Model test cases must define model")

        current_model = self.model
        path_parts = field_path.split("__")
        for index, field_name in enumerate(path_parts):
            try:
                field = current_model._meta.get_field(field_name)
            except FieldDoesNotExist:
                is_terminal_property = index == len(path_parts) - 1 and isinstance(
                    getattr(current_model, field_name, None), property
                )
                self.assertTrue(
                    is_terminal_property,
                    f"{source} references unknown field {field_path!r} on "
                    f"{self.model._meta.label}",
                )
                return

            if index == len(path_parts) - 1:
                return

            related_model = getattr(field, "related_model", None)
            self.assertIsNotNone(
                related_model,
                f"{source} traverses non-related field {field_name!r} in "
                f"{field_path!r}",
            )
            current_model = related_model

    def get_test_scenarios(self) -> list[ModelScenario]:
        """Return model lifecycle scenarios defined by the concrete test case."""
        return []

    def test_model_scenarios(self) -> None:
        """Run each declared model lifecycle scenario in complete isolation."""
        if self.model is None:
            return

        for scenario in self.get_test_scenarios():
            with self.subTest(name=scenario.name):
                with transaction.atomic():
                    try:
                        self._run_model_scenario(scenario)
                    finally:
                        transaction.set_rollback(True)

    def _run_model_scenario(self, scenario: ModelScenario) -> None:
        """Run the lifecycle phases reached by one model scenario."""
        if self.model is None:
            raise AssertionError("Model test cases must define model")

        if scenario.preparation:
            scenario.preparation()

        create_args = self._resolve_model_arguments(scenario.create_args)
        expected_exception = self._expected_exception(scenario, "create")
        if expected_exception:
            self._assert_expected_model_exception(
                expected_exception,
                lambda: self.model.objects.create(**create_args),
            )
            return

        instance = self.model.objects.create(**create_args)
        instance.refresh_from_db()
        if scenario.post_create:
            scenario.post_create(instance)
        self._run_model_validators(
            scenario.create_validators,
            instance,
            phase="create",
            scenario=scenario,
        )

        if scenario.update_args is not None:
            update_args = self._resolve_model_arguments(scenario.update_args)
            for field_name, value in update_args.items():
                setattr(instance, field_name, value)

            expected_exception = self._expected_exception(scenario, "update")
            if expected_exception:
                self._assert_expected_model_exception(
                    expected_exception,
                    instance.save,
                )
                return

            instance.save()
            instance.refresh_from_db()
            self._run_model_validators(
                scenario.update_validators,
                instance,
                phase="update",
                scenario=scenario,
            )

        expected_exception = self._expected_exception(scenario, "delete")
        if not scenario.delete_validators and expected_exception is None:
            return

        deleted_pk = instance.pk
        if expected_exception:
            self._assert_expected_model_exception(
                expected_exception,
                instance.delete,
            )
            return

        instance.delete()
        instance.pk = deleted_pk
        self._run_model_validators(
            scenario.delete_validators,
            instance,
            phase="delete",
            scenario=scenario,
        )

    @staticmethod
    def _resolve_model_arguments(
        arguments: dict[str, Any] | Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        """Resolve eager model arguments or a zero-argument argument factory."""
        return arguments() if callable(arguments) else arguments

    @staticmethod
    def _expected_exception(
        scenario: ModelScenario,
        phase: Literal["create", "update", "delete"],
    ) -> ExpectedModelException | None:
        """Return the exception expectation for one lifecycle phase, if any."""
        return next(
            (
                expected
                for expected in scenario.expected_exceptions
                if expected.phase == phase
            ),
            None,
        )

    def _assert_expected_model_exception(
        self,
        expected: ExpectedModelException,
        operation: Callable[[], Any],
    ) -> None:
        """Run an expected failing operation inside a rollback savepoint."""
        if expected.message_regex is None:
            assertion = self.assertRaises(expected.exception)
        else:
            assertion = self.assertRaisesRegex(
                expected.exception,
                expected.message_regex,
            )

        with assertion:
            with transaction.atomic():
                operation()

    def _run_model_validators(
        self,
        validators: Callable[[Model], bool] | list[Callable[[Model], bool]],
        instance: Model,
        *,
        phase: Literal["create", "update", "delete"],
        scenario: ModelScenario,
    ) -> None:
        """Assert every validator configured for one successful phase."""
        if callable(validators):
            validators = [validators]

        for validator in validators:
            validator_name = getattr(validator, "__name__", type(validator).__name__)
            description = f": {scenario.description}" if scenario.description else ""
            self.assertTrue(
                validator(instance),
                f"{phase.capitalize()} validator {validator_name!r} failed for "
                f"scenario {scenario.name!r}{description}",
            )


# Backwards-compatible name used by existing Bloomerp tests.
BaseBloomerpModelTestCase = BloomerpModelTestCase
