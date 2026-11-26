"""Exercise the shared tutorial player's backward navigation in both modes."""

from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import Locator, expect

from bloomerp.models.tutorial import (
    Tutorial,
    TutorialProgress,
    TutorialRevision,
    TutorialStep,
)
from bloomerp.tests.base import BloomerpE2ETestCase, E2EAction, E2ERequestScenario


class TestTutorialPreviousE2E(BloomerpE2ETestCase):
    """Check Previous boundaries, cross-page resumption, and normal completion."""

    auto_create_customers = False

    def create_tour(self, *, published: bool) -> None:
        """Create a two-step run with a timed second step on another route."""
        tutorial = Tutorial.objects.create(
            name="Navigation tutorial", available_to_all=True
        )
        self.revision = TutorialRevision.objects.create(
            tutorial=tutorial,
            number=1,
            trigger_route="bloomerp_home_view",
            published_at=timezone.now() if published else None,
        )
        TutorialStep.objects.create(
            revision=self.revision, sequence=1, key="home", name="Stay on Home"
        )
        self.last_step = TutorialStep.objects.create(
            revision=self.revision,
            sequence=2,
            key="catalog",
            name="Visit the catalog",
            destination_route="misc_module_my_tutorials",
            advance_mode=TutorialStep.AdvanceMode.DELAY,
            advance_delay_ms=3000,
            hide_next_button=True,
        )

    def prepare_preview(self) -> None:
        """Create the unpublished revision the admin opens through Revisions."""
        self.create_tour(published=False)

    def prepare_playback(self) -> None:
        """Publish a separate fixture for normal learner playback."""
        self.create_tour(published=True)

    def revisions_url(self) -> str:
        """Resolve the authoring view after the scenario creates its tutorial."""
        return reverse(
            "tutorials_detail_revisions_relationship",
            kwargs={"pk": self.revision.tutorial_id},
        )

    def card(self) -> Locator:
        """Return the shared player used in preview and by learners."""
        return self.page.locator("#tutorial-presentation")

    def start_preview(self) -> None:
        """Open the draft and launch its preview on Home."""
        self.page.get_by_role("button", name="More actions", exact=True).click()
        self.page.get_by_role("button", name="Edit", exact=True).click()
        expect(self.page.get_by_role("region", name="Tutorial editor")).to_be_visible()
        preview = self.page.get_by_role("button", name="Preview", exact=True)
        expect(preview).to_be_enabled()
        self.goto(reverse("bloomerp_home_view"))
        preview.click()

    def start_playback(self) -> None:
        """Launch the eligible revision from Home's help menu as a learner."""
        self.page.get_by_role("button", name="Tutorials for this page").click()
        self.page.get_by_role(
            "menuitem", name="Navigation tutorial", exact=True
        ).click()

    def assert_previous(self) -> None:
        """Return across pages, cancel the departing timer, and go forward again."""
        card = self.card()
        previous = card.locator("[data-tutorial-preview-previous]")
        next_button = card.locator("[data-tutorial-preview-next]")
        expect(card.get_by_role("heading", name="Navigation tutorial")).to_be_visible()
        expect(previous).to_be_hidden()
        next_button.click()
        expect(card.get_by_role("heading", name="Stay on Home")).to_be_visible()
        expect(previous).to_be_hidden()
        next_button.click()
        expect(self.page).to_have_url(self.url(reverse("misc_module_my_tutorials")))
        expect(card.get_by_role("heading", name="Visit the catalog")).to_be_visible()
        expect(next_button).to_be_hidden()
        previous.press("Enter")
        expect(self.page).to_have_url(self.url(reverse("bloomerp_home_view")))
        expect(card.get_by_role("heading", name="Stay on Home")).to_be_visible()
        expect(previous).to_be_hidden()
        expect(next_button).to_be_enabled()
        self.assertFalse(
            TutorialProgress.objects.filter(
                revision=self.revision, completed_at__isnull=False
            ).exists()
        )
        next_button.click()
        expect(card.get_by_role("heading", name="Visit the catalog")).to_be_visible()
        expect(card).to_be_hidden(timeout=6000)

    def assert_playback_completed(self) -> None:
        """Verify the normal forward finish records progress on the final step."""
        progress = TutorialProgress.objects.get(
            revision=self.revision, user=self.normal_user
        )
        self.assertIsNotNone(progress.completed_at)
        self.assertEqual(progress.current_step_id, self.last_step.pk)

    def assert_learner_previous(self) -> None:
        """Wait for the learner's eventual completion request after navigating back."""
        with self.expect_response_for(
            reverse("tutorial_playback"), method="PATCH", timeout=15000
        ) as response:
            self.assert_previous()
        self.assertEqual(response.value.status, 204)

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Run the same navigation assertions in preview and real playback."""
        return [
            E2ERequestScenario(
                name="Author preview returns to the previous page and can go forward again",
                user=self.admin_user,
                prepare=self.prepare_preview,
                url=self.revisions_url,
                actions=[
                    E2EAction(
                        name="Open the draft preview", execute=self.start_preview
                    ),
                    E2EAction(
                        name="Use Previous and Next across pages",
                        execute=self.assert_previous,
                    ),
                ],
            ),
            E2ERequestScenario(
                name="Learner can return across pages without completing the tutorial",
                user=self.normal_user,
                prepare=self.prepare_playback,
                url=reverse("bloomerp_home_view"),
                actions=[
                    E2EAction(
                        name="Start an eligible tutorial", execute=self.start_playback
                    ),
                    E2EAction(
                        name="Go back, resume forward playback, and finish",
                        execute=self.assert_learner_previous,
                        validators=self.assert_playback_completed,
                    ),
                ],
            ),
        ]


class TestTutorialAudienceFilterE2E(BloomerpE2ETestCase):
    """Keep genuine conditions validated while allowing an empty tutorial audience filter."""

    auto_create_customers = False

    def prepare_tutorial(self) -> None:
        """Create a tutorial that initially has a valid audience condition."""
        self.tutorial = Tutorial.objects.create(
            name="Audience filter tutorial",
            description="A saved introduction.",
            user_filter=[
                {
                    "connector": "AND",
                    "conditions": [
                        {
                            "field_path": "username",
                            "lookup_id": "equals",
                            "value": "fixture",
                        }
                    ],
                }
            ],
        )

    def detail_url(self) -> str:
        """Locate the tutorial's edit form."""
        return self.tutorial.get_absolute_url()

    def assert_optional_filter(self) -> None:
        """Clear the last saved condition, then distinguish blank from unfinished rows."""
        audience = self.page.locator('[data-name="user_filter"]')
        groups = audience.locator("[data-filter-group]")
        save = self.page.get_by_role("button", name="Save", exact=True)
        expect(
            audience.get_by_role("combobox", name="Field", exact=True)
        ).to_be_visible()
        audience.get_by_role("button", name="Remove condition", exact=True).click()
        expect(groups).to_have_count(0)
        with self.expect_response_for(self.detail_url(), method="POST") as cleared:
            save.click()
        self.assertEqual(cleared.value.status, 200)
        self.tutorial.refresh_from_db()
        self.assertEqual(self.tutorial.user_filter, [])

        self.page.reload(wait_until="domcontentloaded")
        expect(groups).to_have_count(0)
        audience.get_by_role("button", name="Add group", exact=True).click()
        audience.get_by_role("combobox", name="Field", exact=True).select_option(
            label="username"
        )
        save.click()
        expect(
            audience.get_by_text("Complete every filter condition before applying.")
        ).to_be_visible()
        self.tutorial.refresh_from_db()
        self.assertEqual(self.tutorial.user_filter, [])

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Run the filter check through the live tutorial detail form."""
        return [
            E2ERequestScenario(
                name="Tutorial audience can be cleared and an unfinished row still fails",
                user=self.admin_user,
                prepare=self.prepare_tutorial,
                url=self.detail_url,
                actions=[
                    E2EAction(
                        name="Clear and validate conditions",
                        execute=self.assert_optional_filter,
                    )
                ],
            ),
        ]
