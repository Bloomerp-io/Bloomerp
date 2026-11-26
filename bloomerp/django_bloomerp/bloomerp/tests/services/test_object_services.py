from bloomerp.models.definition import BloomerpModelConfig, StringSearchSettings
from bloomerp.services.search_services import string_search_on_queryset
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels


class StringSearchOnQuerysetTests(BaseBloomerpTestCaseWithModels):
    create_foreign_models = True

    def test_string_search_uses_bloomerp_config_related_fields(self):
        had_config = "bloomerp_config" in self.CustomerModel.__dict__
        previous_config = getattr(self.CustomerModel, "bloomerp_config", None)
        self.CustomerModel.bloomerp_config = BloomerpModelConfig(
            string_search_settings=StringSearchSettings(
                string_search_fields=["country__name"],
            )
        )

        try:
            belgium = self.CountryModel.objects.get(name="Belgium")
            matching_customer = self.create_customer(
                first_name="Ada",
                last_name="Lovelace",
                age=36,
                country=belgium,
            )
            self.create_customer(
                first_name="Grace",
                last_name="Hopper",
                age=85,
                country=self.CountryModel.objects.get(name="Brazil"),
            )

            results = string_search_on_queryset(
                self.CustomerModel.objects.all(),
                "Belgium",
            )

            self.assertIn(matching_customer, results)
            self.assertEqual(results.count(), 1)
        finally:
            if not had_config:
                delattr(self.CustomerModel, "bloomerp_config")
            else:
                self.CustomerModel.bloomerp_config = previous_config
    