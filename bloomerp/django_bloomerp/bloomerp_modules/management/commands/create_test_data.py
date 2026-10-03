from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Jamie", "Cameron",
    "Drew", "Avery", "Quinn", "Peyton", "Reese", "Skyler", "Dakota", "Emerson",
    "Harper", "Charlie", "Finley", "Rowan", "Sawyer", "Emery", "Blake", "Quincy",
    "Sage", "Tatum", "Kendall", "Logan", "Micah", "Phoenix", "River", "Shawn",
    "Sydney", "Teagan", "Valentine", "Winter", "Zion", "Arden", "Briar", "Cypress",
    "Peter", "Floor", "Sanne", "Daan", "Lotte", "Jeroen", "Femke", "Thijs", "Roos",
    "Maud", "Koen", "Nina", "Sven", "Lisa", "Jelle", "Tessa", "Wout",
    "Yara", "Lars", "Noah", "Sophie", "Emma", "Lucas", "Mila", "Levi", "Julia",
    "Finn", "Anna", "Daan", "Sara", "Sem", "Eva", "Luuk", "Lina", "Mees",
    "Noud", "Evi", "Thijs", "Lotte", "Ben", "Zoë", "Mats", "Fleur", "Sam",
    "Liv", "Tijn", "Lieke", "Jayden", "Nora", "Jesse", "Yfke", "Julian", "Fay",
    "Adam", "Luna", "Levi", "Isa", "Thomas", "Puck", "Lucas", "Nova", "Dylan",
    "Lana", "Mason", "Fiene", "Ethan", "Jade", "Logan", "Saar", "Caleb", "Livia",
    "Ralph", "Feline", "Nathan", "Lieke", "Ryan", "Yara", "Aaron", "Mara", "Elias",
    "Jade", "Benjamin", "Fleur", "Samuel", "Lina", "David", "Sophie", "Joseph", "Emma",
    "Max", "Daan", "Oscar", "Sanne", "Liam", "Floor", "Milan", "Jeroen", "Elias",
    "Chaim", "Noah", "Resam", "Lisa", "Mick", "Jelle", "Tess", "Wout", "Yara", "Lars", "Noah", "Sophie",
    "Noa", "Levi", "Mila", "Lucas", "Emma", "Finn", "Anna", "Daan", "Sara", "Sem", "Eva", "Luuk", "Lina",
    "Oliver", "Ava", "Elijah", "Isabella", "James", "Sophia", "Benjamin", "Charlotte", "Henry", "Amelia",
    "Alexander", "Mia", "Mason", "Harper", "Michael", "Evelyn", "Ethan", "Abigail", "Daniel", "Emily",
    "Jacob", "Elizabeth", "Logan", "Ella", "Jackson", "Avery", "Sebastian", "Sofia", "Aiden", "Scarlett",
    "Matthew", "Victoria", "Samuel", "Madison", "David", "Chloe", "Joseph", "Penelope", "Carter", "Layla",
    "Thomas", "Lillian", "Charles", "Grace", "Christopher", "Zoey", "Daniel", "Nora", "Matthew", "Riley",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green", "Adams",
    "Janssens", "Bakker", "Visser", "Smit", "Meijer", "De Jong", "Mulder",
    "Vos", "Peters", "Dijkstra", "Kuipers", "Bos", "Kramer", "Brouwer",
    "Veenstra", "Schouten", "Dekker", "Hendriks", "Van Dijk", "Van Den Berg",
    "Van Leeuwen", "Bosch", "Vermeulen", "Kok", "Vos", "Hermans", "Wouters",
    "Peeters", "Maes", "Goossens", "Claes", "Jacobs", "Mertens", "Lemmens",
    "Al Shamrani", "Al-Qahtani", "Al-Farsi", "Al-Mansoori", "Al-Harbi",
    "Al-Zahrani", "Al-Shehri", "Al-Rashid", "Al-Naimi", "Al-Khalifa",
    "Goldsmit", "Goldberg", "Goldstein", "Goldman", "Gold", "Silverman", "Silvers", "Silva",
    "Stern", "Hertzman", "Silverstein", "Goldstein", "Silverstein", "Goldman", "Silversmith", "Goldsmith",
    "Milerson", "Bennett", "Murphy", "Kelly", "Howard", "Rowe", "Henderson", "Coleman",
    "Jenkins", "Perry", "Powell", "Long", "Patterson", "Hughes", "Flores", "Washington",
    "Butler", "Simmons", "Bryant", "Alexander", "Russell", "Griffin", "Hayes", "Myers",
    "Ford", "Hamilton", "Graham", "Sullivan", "Wallace", "Woods", "Cole", "West",
    "Jordan", "Owens", "Reynolds", "Fisher", "Ellis", "Harper", "Mason", "Howell",
    "Doyle", "Meadows", "Herrera", "Henson", "Wilkins", "Dyer", "Reeves", "Chase",
    "Crane", "Dalton", "Everett", "Gentry", "Gibbs", "Haynes", "Hodges", "Holmes",
    "Hudson", "Kline", "Knox", "Lacey", "Larsen", "Latham", "Lawson", "Leach",
    "Rosenberg", "Eisenberg", "Feldman", "Friedman", "Kaplan", "Rosen", "Mendelsohn",
    "Lipman", "Wasserstein", "Weintraub", "Blumenthal", "Berkowitz", "Horowitz", "Levin", "Zuckerman",
]


class Command(BaseCommand):
    help = "Create test data for bloomerp_modules dynamic models."
    BASE_EMPLOYEE_COUNT = 10000

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Create test data even if records already exist.",
        )
        parser.add_argument(
            "--employee-multiplier",
            type=float,
            default=1.0,
            help=(
                "Scale employee generation count. "
                "For example, --employee-multiplier 10 creates about 10x more employees."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Create linked sample records and a runnable CRM qualification workflow."""
        force = options.get("force", False)
        employee_multiplier = max(options.get("employee_multiplier", 1.0), 0.0)

        self._create_manufacturing_master_data(force)
        self._create_hrm_data(force, employee_multiplier)
        self._create_user_data(force)
        self._create_crm_data(force)
        self._create_finance_data(force)
        self._create_demo_workflow()

        self.stdout.write(self.style.SUCCESS("Test data creation complete."))

    def _create_demo_workflow(self) -> None:
        """Seed one manual lead qualification flow and a successful example run."""
        from bloomerp.automation.run import run_workflow
        from bloomerp.models.automation.workflow import Workflow
        from bloomerp.models.automation.workflow_node import WorkflowNode
        from bloomerp.models.automation.workflow_run import WorkflowRunStatus

        with transaction.atomic():
            name = "Demo: Qualify a CRM lead"
            if Workflow.objects.filter(name=name).exists():
                return

            workflow = Workflow.objects.create(
                name=name,
                active=True,
                run_asynchronously=False,
                enable_logging=True,
            )
            trigger = WorkflowNode.objects.create(
                workflow=workflow,
                name="New lead details",
                type="TRIGGER",
                sub_type="HUMAN_TRIGGER",
                parameters={
                    "data": {
                        "lead_name": "Acme Expansion",
                        "account_name": "Acme Manufacturing",
                        "estimated_value": 25000,
                    }
                },
                pos_x=80,
                pos_y=180,
            )
            decision = WorkflowNode.objects.create(
                workflow=workflow,
                name="Is the lead worth 20,000 or more?",
                type="FLOW",
                sub_type="IF_CONDITION",
                parameters={
                    "field": "estimated_value",
                    "operator": "greater_than_or_equal",
                    "value": "20000",
                },
                pos_x=360,
                pos_y=180,
            )
            high_priority = WorkflowNode.objects.create(
                workflow=workflow,
                name="Prepare discovery call",
                type="ACTION",
                sub_type="ENRICH_DATA",
                parameters={
                    "data": {
                        "priority": "high",
                        "next_step": "Schedule a discovery call",
                    }
                },
                pos_x=680,
                pos_y=80,
            )
            standard_priority = WorkflowNode.objects.create(
                workflow=workflow,
                name="Prepare qualification email",
                type="ACTION",
                sub_type="ENRICH_DATA",
                parameters={
                    "data": {
                        "priority": "normal",
                        "next_step": "Send a qualification email",
                    }
                },
                pos_x=680,
                pos_y=280,
            )
            workflow.connect_nodes(trigger, decision)
            workflow.connect_nodes(decision, high_priority, output_port="true")
            workflow.connect_nodes(decision, standard_priority, output_port="false")

            example_run = run_workflow(workflow, {})
            if example_run is None or example_run.status != WorkflowRunStatus.SUCCEEDED:
                raise RuntimeError("The demo lead qualification workflow did not complete")

    def _get_model(self, model_name: str):
        try:
            return apps.get_model("bloomerp_modules", model_name)
        except LookupError:
            self.stdout.write(self.style.WARNING(f"Model '{model_name}' not found. Skipping."))
            return None

    def _should_create(self, model, force: bool) -> bool:
        if model is None:
            return False
        if force:
            return True
        return not model.objects.exists()

    def _create_records(self, model, records, lookup_fields):
        created_objects = []
        if model is None:
            return created_objects
        for record in records:
            lookup = {field: record[field] for field in lookup_fields}
            defaults = {key: value for key, value in record.items() if key not in lookup}
            obj, _created = model.objects.get_or_create(**lookup, defaults=defaults)
            created_objects.append(obj)
        return created_objects

    def _create_manufacturing_master_data(self, force: bool) -> None:
        unit_model = self._get_model("UnitOfMeasure")
        warehouse_model = self._get_model("Warehouse")
        location_model = self._get_model("Location")
        product_model = self._get_model("Product")

        units = []
        if self._should_create(unit_model, force):
            units = self._create_records(
                unit_model,
                [
                    {
                        "name": "Each",
                        "symbol": "EA",
                        "category": "Unit",
                        "ratio_to_base": Decimal("1.0"),
                    },
                    {
                        "name": "Box",
                        "symbol": "BOX",
                        "category": "Packaging",
                        "ratio_to_base": Decimal("10.0"),
                    },
                    {
                        "name": "Kilogram",
                        "symbol": "KG",
                        "category": "Weight",
                        "ratio_to_base": Decimal("1.0"),
                    },
                ],
                ["name"],
            )
        else:
            self.stdout.write("Skipping Unit of Measure data (already exists).")

        warehouses = []
        if self._should_create(warehouse_model, force):
            warehouses = self._create_records(
                warehouse_model,
                [
                    {
                        "code": "WH-NORTH",
                        "name": "North Warehouse",
                        "address": "100 North Ave, Springfield",
                        "is_default": True,
                    },
                    {
                        "code": "WH-SOUTH",
                        "name": "South Warehouse",
                        "address": "200 South Ave, Springfield",
                        "is_default": False,
                    },
                ],
                ["code"],
            )
        else:
            self.stdout.write("Skipping Warehouse data (already exists).")

        if location_model and warehouses:
            self._create_records(
                location_model,
                [
                    {
                        "warehouse": warehouses[0],
                        "code": "STOCK-01",
                        "name": "Main Stock",
                        "location_type": "stock",
                        "is_active": True,
                    },
                    {
                        "warehouse": warehouses[0],
                        "code": "INPUT-01",
                        "name": "Inbound Dock",
                        "location_type": "input",
                        "is_active": True,
                    },
                    {
                        "warehouse": warehouses[1],
                        "code": "OUTPUT-01",
                        "name": "Outbound Dock",
                        "location_type": "output",
                        "is_active": True,
                    },
                ],
                ["warehouse", "code"],
            )

        if product_model and units and warehouses:
            self._create_records(
                product_model,
                [
                    {
                        "code": "PROD-100",
                        "name": "Widget A",
                        "description": "Standard widget for general use.",
                        "type": "manufactured",
                        "uom": units[0],
                        "default_warehouse": warehouses[0],
                        "is_active": True,
                        "lead_time_days": 5,
                        "safety_stock_quantity": Decimal("10"),
                        "reorder_point_quantity": Decimal("20"),
                        "standard_lot_size": Decimal("50"),
                        "tracking_method": "lot",
                        "standard_cost": Decimal("12.50"),
                        "sales_price": Decimal("25.00"),
                    },
                    {
                        "code": "PROD-200",
                        "name": "Gadget B",
                        "description": "Purchased gadget with multiple variants.",
                        "type": "purchased",
                        "uom": units[1],
                        "default_warehouse": warehouses[1],
                        "is_active": True,
                        "lead_time_days": 2,
                        "safety_stock_quantity": Decimal("5"),
                        "reorder_point_quantity": Decimal("10"),
                        "standard_lot_size": Decimal("20"),
                        "tracking_method": "serial",
                        "standard_cost": Decimal("30.00"),
                        "sales_price": Decimal("55.00"),
                    },
                ],
                ["code"],
            )
        elif product_model:
            self.stdout.write("Skipping Product data (missing units or warehouses).")

    def _create_hrm_data(self, force: bool, employee_multiplier: float = 1.0) -> None:
        person_model = self._get_model("Person")
        job_title_model = self._get_model("JobTitle")
        cost_center_model = self._get_model("HrCostCenter")
        office_location_model = self._get_model("OfficeLocation")
        department_model = self._get_model("Department")
        team_model = self._get_model("Team")
        employee_model = self._get_model("Employee")
        employee_contract_model = self._get_model("EmployeeContract")

        job_opening_model = self._get_model("JobOpening")
        candidate_model = self._get_model("Candidate")
        application_model = self._get_model("Application")
        interview_model = self._get_model("Interview")
        interview_feedback_model = self._get_model("InterviewFeedback")
        hiring_decision_model = self._get_model("HiringDecision")
        offer_model = self._get_model("Offer")
        offer_approval_model = self._get_model("OfferApproval")

        onboarding_process_model = self._get_model("OnboardingProcess")
        onboarding_task_model = self._get_model("OnboardingTask")
        onboarding_task_assignment_model = self._get_model("OnboardingTaskAssignment")
        offboarding_process_model = self._get_model("OffboardingProcess")
        exit_reason_model = self._get_model("ExitReason")
        exit_interview_model = self._get_model("ExitInterview")

        work_schedule_model = self._get_model("WorkSchedule")
        attendance_record_model = self._get_model("AttendanceRecord")
        time_entry_model = self._get_model("TimeEntry")
        overtime_rule_model = self._get_model("OvertimeRule")
        leave_type_model = self._get_model("LeaveType")
        leave_policy_model = self._get_model("LeavePolicy")
        leave_request_model = self._get_model("LeaveRequest")
        leave_balance_model = self._get_model("LeaveBalance")
        public_holiday_model = self._get_model("PublicHoliday")

        performance_cycle_model = self._get_model("PerformanceCycle")
        goal_model = self._get_model("Goal")
        goal_progress_model = self._get_model("GoalProgress")
        performance_review_model = self._get_model("PerformanceReview")
        review_question_model = self._get_model("ReviewQuestion")
        review_response_model = self._get_model("ReviewResponse")
        peer_feedback_model = self._get_model("PeerFeedback")

        persons = []
        if person_model and self._should_create(person_model, force):
            persons = self._create_records(
                person_model,
                [
                    {
                        "first_name": "Avery",
                        "last_name": "Nguyen",
                        "middle_name": "L.",
                        "email": "avery.nguyen@bloomerp.test",
                        "phone": "+1-555-1001",
                        "date_of_birth": date(1990, 5, 12),
                        "person_type": "employee",
                        "status": "active",
                    },
                    {
                        "first_name": "Jordan",
                        "last_name": "Patel",
                        "middle_name": None,
                        "email": "jordan.patel@bloomerp.test",
                        "phone": "+1-555-1002",
                        "date_of_birth": date(1986, 11, 3),
                        "person_type": "employee",
                        "status": "active",
                    },
                ],
                ["first_name", "last_name"],
            )

        job_titles = []
        if job_title_model and self._should_create(job_title_model, force):
            job_titles = self._create_records(
                job_title_model,
                [
                    {"title": "Operations Analyst", "code": "OPS-ANL", "level": "L2"},
                    {"title": "HR Specialist", "code": "HR-SPC", "level": "L2"},
                    {"title": "QA Contractor", "code": "QA-CTR", "level": "L1"},
                ],
                ["title"],
            )
        elif job_title_model:
            job_titles = list(job_title_model.objects.all()[:3])

        cost_centers = []
        if cost_center_model and self._should_create(cost_center_model, force):
            cost_centers = self._create_records(
                cost_center_model,
                [
                    {"code": "CC-OPS", "name": "Operations"},
                    {"code": "CC-HR", "name": "People"},
                    {"code": "CC-QLT", "name": "Quality"},
                ],
                ["code"],
            )
        elif cost_center_model:
            cost_centers = list(cost_center_model.objects.all()[:3])

        office_locations = []
        if office_location_model and self._should_create(office_location_model, force):
            office_locations = self._create_records(
                office_location_model,
                [
                    {
                        "name": "Springfield HQ",
                        "code": "HQ",
                        "city": "Springfield",
                        "country": "USA",
                        "phone": "+1-555-2000",
                        "is_active": True,
                    },
                    {
                        "name": "Remote Hub",
                        "code": "REMOTE",
                        "city": "Remote",
                        "country": "USA",
                        "phone": "+1-555-2001",
                        "is_active": True,
                    },
                ],
                ["name"],
            )
        elif office_location_model:
            office_locations = list(office_location_model.objects.all()[:2])

        departments = []
        if department_model and self._should_create(department_model, force):
            departments = self._create_records(
                department_model,
                [
                    {
                        "name": "Operations",
                        "code": "OPS",
                        "cost_center": cost_centers[0] if cost_centers else None,
                        "is_active": True,
                    },
                    {
                        "name": "People",
                        "code": "HR",
                        "cost_center": cost_centers[1] if cost_centers else None,
                        "is_active": True,
                    },
                    {
                        "name": "Quality",
                        "code": "QA",
                        "cost_center": cost_centers[2] if cost_centers else None,
                        "is_active": True,
                    },
                ],
                ["name"],
            )
        elif department_model:
            departments = list(department_model.objects.all()[:3])

        teams = []
        if team_model and self._should_create(team_model, force):
            teams = self._create_records(
                team_model,
                [
                    {
                        "name": "Ops Excellence",
                        "department": departments[0] if departments else None,
                        "is_active": True,
                    },
                    {
                        "name": "People Ops",
                        "department": departments[1] if departments else None,
                        "is_active": True,
                    },
                ],
                ["name"],
            )
        elif team_model:
            teams = list(team_model.objects.all()[:2])

        employees = []
        if employee_model and self._should_create(employee_model, force):
            import random

            records = []
            employee_target = max(1, int(self.BASE_EMPLOYEE_COUNT * employee_multiplier))

            email_extensions = ["bloomerp.test", "example.com", "testmail.com", "mailtest.org"]

            self.stdout.write(f"Generating approximately {employee_target} employees...")
            for i in range(employee_target):
                first_name = random.choice(FIRST_NAMES)
                last_name = random.choice(LAST_NAMES)
                email = (
                    f"{first_name.lower()}.{last_name.lower()}.{i}"
                    f"@{random.choice(email_extensions)}"
                )

                record = {
                    "first_name": first_name,
                    "last_name": last_name,
                    "middle_name": random.choice([None, "A.", "B.", "C.", "D.", "E."]),
                    "date_of_birth": date(random.randint(1980, 2005), random.randint(1, 12), random.randint(1, 28)),
                    "email": email,
                    "phone": f"+1-555-{random.randint(1000, 9999)}",
                    "job_title": random.choice(job_titles) if job_titles else None,
                    "department": random.choice(departments) if departments else None,
                    "team": random.choice(teams) if teams else None,
                    "office_location": random.choice(office_locations) if office_locations else None,
                    "cost_center": random.choice(cost_centers) if cost_centers else None,
                    "employment_type": random.choice(["full_time", "part_time", "contractor", "intern"]),
                    "hire_date": date.today() - timedelta(days=random.randint(30, 365 * 10)),
                    "status": "active",
                }
                records.append(record)

            employees = self._create_records(
                employee_model,
                records,
                ["email"],
            )
        elif employee_model:
            employees = list(employee_model.objects.all()[:3])

        if employee_contract_model and employees and self._should_create(employee_contract_model, force):
            self._create_records(
                employee_contract_model,
                [
                    {
                        "employee": employees[0],
                        "contract_type": "permanent",
                        "start_date": date(2020, 3, 15),
                        "status": "active",
                        "salary": Decimal("65000"),
                        "currency": "USD",
                        "signed_date": date(2020, 3, 10),
                    },
                    {
                        "employee": employees[1],
                        "contract_type": "fixed_term",
                        "start_date": date(2019, 7, 1),
                        "end_date": date(2025, 7, 1),
                        "status": "active",
                        "salary": Decimal("52000"),
                        "currency": "USD",
                    },
                ],
                ["employee"],
            )

        if job_opening_model and self._should_create(job_opening_model, force):
            job_openings = self._create_records(
                job_opening_model,
                [
                    {
                        "title": "Operations Analyst",
                        "job_title": job_titles[0] if job_titles else None,
                        "department": departments[0] if departments else None,
                        "location": office_locations[0] if office_locations else None,
                        "openings_count": 1,
                        "status": "open",
                        "posted_date": date.today() - timedelta(days=14),
                    }
                ],
                ["title"],
            )
        else:
            job_openings = job_opening_model.objects.all()[:1] if job_opening_model else []

        if candidate_model and self._should_create(candidate_model, force):
            candidates = self._create_records(
                candidate_model,
                [
                    {
                        "person": persons[0] if persons else None,
                        "first_name": "Riley",
                        "last_name": "Chen",
                        "email": "riley.chen@candidate.test",
                        "phone": "+1-555-3001",
                        "source": "referral",
                        "status": "interviewing",
                    }
                ],
                ["email"],
            )
        else:
            candidates = candidate_model.objects.all()[:1] if candidate_model else []

        if application_model and job_openings and candidates and self._should_create(application_model, force):
            applications = self._create_records(
                application_model,
                [
                    {
                        "candidate": candidates[0],
                        "job_opening": job_openings[0],
                        "applied_date": date.today() - timedelta(days=10),
                        "status": "interview",
                        "resume_link": "https://example.com/resume.pdf",
                    }
                ],
                ["candidate", "job_opening"],
            )
        else:
            applications = application_model.objects.all()[:1] if application_model else []

        if interview_model and applications and self._should_create(interview_model, force):
            interviews = self._create_records(
                interview_model,
                [
                    {
                        "application": applications[0],
                        "scheduled_at": timezone.now() + timedelta(days=2),
                        "interview_type": "video",
                        "location": "Zoom",
                        "status": "scheduled",
                    }
                ],
                ["application"],
            )
        else:
            interviews = interview_model.objects.all()[:1] if interview_model else []

        if interview_feedback_model and interviews and self._should_create(interview_feedback_model, force):
            self._create_records(
                interview_feedback_model,
                [
                    {
                        "interview": interviews[0],
                        "rating": 4,
                        "recommendation": "hire",
                        "comments": "Strong analytical skills.",
                    }
                ],
                ["interview"],
            )

        if hiring_decision_model and applications and self._should_create(hiring_decision_model, force):
            self._create_records(
                hiring_decision_model,
                [
                    {
                        "application": applications[0],
                        "decision": "hire",
                        "decided_at": timezone.now(),
                    }
                ],
                ["application"],
            )

        if offer_model and applications and self._should_create(offer_model, force):
            offers = self._create_records(
                offer_model,
                [
                    {
                        "application": applications[0],
                        "offer_date": date.today(),
                        "proposed_start_date": date.today() + timedelta(days=30),
                        "salary": Decimal("60000"),
                        "currency": "USD",
                        "status": "sent",
                    }
                ],
                ["application"],
            )
        else:
            offers = offer_model.objects.all()[:1] if offer_model else []

        if offer_approval_model and offers and self._should_create(offer_approval_model, force):
            self._create_records(
                offer_approval_model,
                [
                    {
                        "offer": offers[0],
                        "status": "approved",
                        "decided_at": timezone.now(),
                        "notes": "Approved by HR.",
                    }
                ],
                ["offer"],
            )

        if exit_reason_model and self._should_create(exit_reason_model, force):
            exit_reasons = self._create_records(
                exit_reason_model,
                [
                    {"name": "Resignation", "code": "RESIGN"},
                    {"name": "Retirement", "code": "RETIRE"},
                ],
                ["name"],
            )
        else:
            exit_reasons = exit_reason_model.objects.all()[:2] if exit_reason_model else []

        if onboarding_process_model and employees and self._should_create(onboarding_process_model, force):
            onboarding_processes = self._create_records(
                onboarding_process_model,
                [
                    {
                        "employee": employees[2] if len(employees) > 2 else employees[0],
                        "start_date": date.today() - timedelta(days=3),
                        "status": "in_progress",
                    }
                ],
                ["employee"],
            )
        else:
            onboarding_processes = onboarding_process_model.objects.all()[:1] if onboarding_process_model else []

        if onboarding_task_model and self._should_create(onboarding_task_model, force):
            onboarding_tasks = self._create_records(
                onboarding_task_model,
                [
                    {"name": "Complete paperwork", "category": "HR", "default_due_days": 1},
                    {"name": "Setup workstation", "category": "IT", "default_due_days": 2},
                ],
                ["name"],
            )
        else:
            onboarding_tasks = onboarding_task_model.objects.all()[:2] if onboarding_task_model else []

        if (
            onboarding_task_assignment_model
            and onboarding_processes
            and onboarding_tasks
            and self._should_create(onboarding_task_assignment_model, force)
        ):
            self._create_records(
                onboarding_task_assignment_model,
                [
                    {
                        "onboarding_process": onboarding_processes[0],
                        "onboarding_task": onboarding_tasks[0],
                        "due_date": date.today() + timedelta(days=1),
                        "status": "in_progress",
                    }
                ],
                ["onboarding_process", "onboarding_task"],
            )

        if offboarding_process_model and employees and self._should_create(offboarding_process_model, force):
            offboarding_processes = self._create_records(
                offboarding_process_model,
                [
                    {
                        "employee": employees[1] if len(employees) > 1 else employees[0],
                        "start_date": date.today() - timedelta(days=7),
                        "status": "in_progress",
                        "exit_reason": exit_reasons[0] if exit_reasons else None,
                    }
                ],
                ["employee"],
            )
        else:
            offboarding_processes = offboarding_process_model.objects.all()[:1] if offboarding_process_model else []

        if exit_interview_model and offboarding_processes and self._should_create(exit_interview_model, force):
            self._create_records(
                exit_interview_model,
                [
                    {
                        "offboarding_process": offboarding_processes[0],
                        "scheduled_at": timezone.now() + timedelta(days=1),
                        "notes": "Exit interview scheduled.",
                    }
                ],
                ["offboarding_process"],
            )

        if work_schedule_model and self._should_create(work_schedule_model, force):
            work_schedules = self._create_records(
                work_schedule_model,
                [
                    {
                        "name": "Standard 9-5",
                        "start_time": timezone.datetime(2024, 1, 1, 9, 0).time(),
                        "end_time": timezone.datetime(2024, 1, 1, 17, 0).time(),
                        "work_days": "Mon-Fri",
                        "is_active": True,
                    }
                ],
                ["name"],
            )
        else:
            work_schedules = work_schedule_model.objects.all()[:1] if work_schedule_model else []

        if attendance_record_model and employees and self._should_create(attendance_record_model, force):
            self._create_records(
                attendance_record_model,
                [
                    {
                        "employee": employees[0],
                        "attendance_date": date.today() - timedelta(days=1),
                        "status": "present",
                        "check_in": timezone.datetime(2024, 1, 1, 9, 5).time(),
                        "check_out": timezone.datetime(2024, 1, 1, 17, 2).time(),
                    }
                ],
                ["employee", "attendance_date"],
            )

        if time_entry_model and employees and self._should_create(time_entry_model, force):
            self._create_records(
                time_entry_model,
                [
                    {
                        "employee": employees[0],
                        "work_date": date.today() - timedelta(days=2),
                        "hours": Decimal("7.5"),
                        "work_type": "Project Work",
                    }
                ],
                ["employee", "work_date"],
            )

        if overtime_rule_model and self._should_create(overtime_rule_model, force):
            self._create_records(
                overtime_rule_model,
                [
                    {
                        "name": "Standard OT",
                        "minimum_hours": Decimal("40"),
                        "rate_multiplier": Decimal("1.5"),
                        "is_active": True,
                    }
                ],
                ["name"],
            )

        if leave_type_model and self._should_create(leave_type_model, force):
            leave_types = self._create_records(
                leave_type_model,
                [
                    {"name": "Annual Leave", "code": "AL", "category": "paid", "is_active": True},
                    {"name": "Sick Leave", "code": "SL", "category": "sick", "is_active": True},
                ],
                ["code"],
            )
        else:
            leave_types = leave_type_model.objects.all()[:2] if leave_type_model else []

        if leave_policy_model and leave_types and self._should_create(leave_policy_model, force):
            leave_policies = self._create_records(
                leave_policy_model,
                [
                    {
                        "name": "Annual Leave Policy",
                        "leave_type": leave_types[0],
                        "accrual_rate": Decimal("1.5"),
                        "max_balance": Decimal("20"),
                    }
                ],
                ["name"],
            )
        else:
            leave_policies = leave_policy_model.objects.all()[:1] if leave_policy_model else []

        if leave_request_model and employees and leave_types and self._should_create(leave_request_model, force):
            self._create_records(
                leave_request_model,
                [
                    {
                        "employee": employees[0],
                        "leave_type": leave_types[0],
                        "start_date": date.today() + timedelta(days=5),
                        "end_date": date.today() + timedelta(days=7),
                        "status": "requested",
                        "reason": "Family vacation",
                    }
                ],
                ["employee", "start_date"],
            )

        if leave_balance_model and employees and leave_types and self._should_create(leave_balance_model, force):
            self._create_records(
                leave_balance_model,
                [
                    {
                        "employee": employees[0],
                        "leave_type": leave_types[0],
                        "balance": Decimal("12"),
                        "as_of_date": date.today(),
                    }
                ],
                ["employee", "leave_type"],
            )

        if public_holiday_model and self._should_create(public_holiday_model, force):
            self._create_records(
                public_holiday_model,
                [
                    {
                        "name": "New Year's Day",
                        "date": date(date.today().year, 1, 1),
                        "location": office_locations[0] if office_locations else None,
                        "is_active": True,
                    }
                ],
                ["name", "date"],
            )

        if performance_cycle_model and self._should_create(performance_cycle_model, force):
            performance_cycles = self._create_records(
                performance_cycle_model,
                [
                    {
                        "name": f"{date.today().year} Annual Cycle",
                        "start_date": date(date.today().year, 1, 1),
                        "end_date": date(date.today().year, 12, 31),
                        "status": "active",
                    }
                ],
                ["name"],
            )
        else:
            performance_cycles = performance_cycle_model.objects.all()[:1] if performance_cycle_model else []

        if goal_model and employees and performance_cycles and self._should_create(goal_model, force):
            goals = self._create_records(
                goal_model,
                [
                    {
                        "employee": employees[0],
                        "performance_cycle": performance_cycles[0],
                        "title": "Improve on-time delivery",
                        "status": "in_progress",
                        "target_date": date.today() + timedelta(days=90),
                    }
                ],
                ["employee", "title"],
            )
        else:
            goals = goal_model.objects.all()[:1] if goal_model else []

        if goal_progress_model and goals and self._should_create(goal_progress_model, force):
            self._create_records(
                goal_progress_model,
                [
                    {
                        "goal": goals[0],
                        "progress_percent": Decimal("35"),
                        "update_date": date.today(),
                        "notes": "On track with milestones.",
                    }
                ],
                ["goal"],
            )

        if performance_review_model and employees and performance_cycles and self._should_create(performance_review_model, force):
            performance_reviews = self._create_records(
                performance_review_model,
                [
                    {
                        "employee": employees[0],
                        "performance_cycle": performance_cycles[0],
                        "status": "in_review",
                        "overall_rating": Decimal("4.2"),
                        "summary": "Consistent performance with strong ownership.",
                    }
                ],
                ["employee", "performance_cycle"],
            )
        else:
            performance_reviews = performance_review_model.objects.all()[:1] if performance_review_model else []

        if review_question_model and self._should_create(review_question_model, force):
            review_questions = self._create_records(
                review_question_model,
                [
                    {
                        "performance_cycle": performance_cycles[0] if performance_cycles else None,
                        "question_text": "How did the employee perform against goals?",
                        "category": "Goals",
                        "is_active": True,
                    }
                ],
                ["question_text"],
            )
        else:
            review_questions = review_question_model.objects.all()[:1] if review_question_model else []

        if review_response_model and performance_reviews and review_questions and self._should_create(review_response_model, force):
            self._create_records(
                review_response_model,
                [
                    {
                        "performance_review": performance_reviews[0],
                        "question": review_questions[0],
                        "rating": 4,
                        "response_text": "Delivered key milestones ahead of schedule.",
                    }
                ],
                ["performance_review", "question"],
            )

        if peer_feedback_model and employees and performance_cycles and self._should_create(peer_feedback_model, force):
            self._create_records(
                peer_feedback_model,
                [
                    {
                        "employee": employees[0],
                        "performance_cycle": performance_cycles[0],
                        "rating": 5,
                        "feedback": "Great collaborator and mentor.",
                    }
                ],
                ["employee", "performance_cycle"],
            )

    def _create_finance_data(self, force: bool) -> None:
        bank_accounts = self._create_finance_bank_accounts(force)
        self._create_general_ledger_data(force, bank_accounts)

    def _create_finance_bank_accounts(self, force: bool) -> dict[str, object]:
        bank_account_model = self._get_model("BankAccount")
        if bank_account_model is None:
            return {}

        bank_records = [
            {
                "bank_name": "First National Bank",
                "account_name": "Bloomerp Operating",
                "account_number": "111222333",
                "account_type": "checking",
                "currency": "USD",
                "iban": "US00FNB0000111222333",
                "swift_code": "FNBUS33",
                "branch": "Downtown",
                "opening_balance": Decimal("90000.00"),
                "last_reconciled_date": date.today() - timedelta(days=5),
                "last_reconciled_balance": Decimal("103842.17"),
                "is_primary": True,
                "is_active": True,
                "notes": "Primary operating account used for payroll, suppliers, and customer receipts.",
            },
            {
                "bank_name": "City Credit Union",
                "account_name": "Bloomerp Reserve Savings",
                "account_number": "444555666",
                "account_type": "savings",
                "currency": "USD",
                "iban": None,
                "swift_code": "CCUS44",
                "branch": "Uptown",
                "opening_balance": Decimal("20000.00"),
                "last_reconciled_date": date.today() - timedelta(days=12),
                "last_reconciled_balance": Decimal("22400.00"),
                "is_primary": False,
                "is_active": True,
                "notes": "Liquidity reserve for tax payments and planned equipment purchases.",
            },
        ]
        self._create_records(
            bank_account_model,
            bank_records,
            ["bank_name", "account_number"],
        )
        return {
            record["account_number"]: bank_account_model.objects.get(
                account_number=record["account_number"]
            )
            for record in bank_records
        }

    def _create_general_ledger_data(self, force: bool, bank_accounts: dict[str, object]) -> None:
        account_model = self._get_model("Account")
        fiscal_period_model = self._get_model("FiscalPeriod")
        journal_model = self._get_model("Journal")
        journal_entry_model = self._get_model("JournalEntry")
        journal_entry_line_model = self._get_model("JournalEntryLine")
        gl_transaction_model = self._get_model("GLTransaction")
        account_balance_model = self._get_model("AccountBalance")
        budget_model = self._get_model("Budget")

        required_models = (
            account_model,
            fiscal_period_model,
            journal_model,
            journal_entry_model,
            journal_entry_line_model,
            gl_transaction_model,
        )
        if any(model is None for model in required_models):
            self.stdout.write(self.style.WARNING("Skipping general ledger data (required model missing)."))
            return

        today = date.today()
        current_year = today.year
        current_month = today.month
        ledger_user = get_user_model().objects.order_by("pk").first()
        posting_timestamp = timezone.now()

        account_rows = [
            {"code": "1000", "name": "Assets", "type": "ASSET", "subtype": "CURRENT_ASSET", "normal": "DEBIT", "description": "All company assets", "parent": None},
            {"code": "1010", "name": "Operating Checking Account", "type": "ASSET", "subtype": "CURRENT_ASSET", "normal": "DEBIT", "description": "Primary operating cash account", "parent": "1000", "bank": "111222333", "reconcile": True},
            {"code": "1020", "name": "Reserve Savings Account", "type": "ASSET", "subtype": "CURRENT_ASSET", "normal": "DEBIT", "description": "Cash reserve account", "parent": "1000", "bank": "444555666", "reconcile": True},
            {"code": "1100", "name": "Accounts Receivable", "type": "ASSET", "subtype": "CURRENT_ASSET", "normal": "DEBIT", "description": "Amounts due from customers", "parent": "1000"},
            {"code": "1200", "name": "Inventory", "type": "ASSET", "subtype": "CURRENT_ASSET", "normal": "DEBIT", "description": "Finished goods and purchased components", "parent": "1000"},
            {"code": "1300", "name": "Prepaid Expenses", "type": "ASSET", "subtype": "CURRENT_ASSET", "normal": "DEBIT", "description": "Insurance and service contracts paid in advance", "parent": "1000"},
            {"code": "1400", "name": "Input Tax Receivable", "type": "ASSET", "subtype": "CURRENT_ASSET", "normal": "DEBIT", "description": "Recoverable tax on supplier invoices", "parent": "1000", "tax": "PURCHASE-8"},
            {"code": "1500", "name": "Property and Equipment", "type": "ASSET", "subtype": "FIXED_ASSET", "normal": "DEBIT", "description": "Long-lived operating assets", "parent": "1000"},
            {"code": "1510", "name": "Computer Equipment", "type": "ASSET", "subtype": "FIXED_ASSET", "normal": "DEBIT", "description": "Laptops, servers, and office equipment", "parent": "1500"},
            {"code": "1520", "name": "Accumulated Depreciation", "type": "ASSET", "subtype": "FIXED_ASSET", "normal": "CREDIT", "description": "Accumulated depreciation on equipment", "parent": "1500"},
            {"code": "2000", "name": "Liabilities", "type": "LIABILITY", "subtype": "CURRENT_LIABILITY", "normal": "CREDIT", "description": "All company liabilities", "parent": None},
            {"code": "2010", "name": "Accounts Payable", "type": "LIABILITY", "subtype": "CURRENT_LIABILITY", "normal": "CREDIT", "description": "Amounts owed to vendors", "parent": "2000"},
            {"code": "2020", "name": "Payroll Taxes Payable", "type": "LIABILITY", "subtype": "CURRENT_LIABILITY", "normal": "CREDIT", "description": "Payroll withholdings awaiting remittance", "parent": "2000"},
            {"code": "2030", "name": "Sales Tax Payable", "type": "LIABILITY", "subtype": "CURRENT_LIABILITY", "normal": "CREDIT", "description": "Tax collected from customers", "parent": "2000", "tax": "SALES-8"},
            {"code": "3000", "name": "Equity", "type": "EQUITY", "subtype": "OWNER_EQUITY", "normal": "CREDIT", "description": "Shareholders' equity", "parent": None},
            {"code": "3010", "name": "Common Stock", "type": "EQUITY", "subtype": "OWNER_EQUITY", "normal": "CREDIT", "description": "Issued common shares", "parent": "3000"},
            {"code": "3020", "name": "Retained Earnings", "type": "EQUITY", "subtype": "RETAINED_EARNINGS", "normal": "CREDIT", "description": "Accumulated retained earnings", "parent": "3000"},
            {"code": "4000", "name": "Revenue", "type": "REVENUE", "subtype": "OPERATING_REVENUE", "normal": "CREDIT", "description": "Operating revenue", "parent": None},
            {"code": "4010", "name": "Product Sales", "type": "REVENUE", "subtype": "OPERATING_REVENUE", "normal": "CREDIT", "description": "Revenue from manufactured products", "parent": "4000"},
            {"code": "4020", "name": "Implementation Services", "type": "REVENUE", "subtype": "OPERATING_REVENUE", "normal": "CREDIT", "description": "Professional services revenue", "parent": "4000"},
            {"code": "5000", "name": "Cost of Goods Sold", "type": "EXPENSE", "subtype": "COST_OF_GOODS_SOLD", "normal": "DEBIT", "description": "Cost of products shipped to customers", "parent": None},
            {"code": "6000", "name": "Operating Expenses", "type": "EXPENSE", "subtype": "OPERATING_EXPENSE", "normal": "DEBIT", "description": "Operating expenses", "parent": None},
            {"code": "6010", "name": "Salaries and Wages", "type": "EXPENSE", "subtype": "OPERATING_EXPENSE", "normal": "DEBIT", "description": "Employee payroll expense", "parent": "6000", "department": "Operations"},
            {"code": "6020", "name": "Rent Expense", "type": "EXPENSE", "subtype": "OPERATING_EXPENSE", "normal": "DEBIT", "description": "Office and warehouse rent", "parent": "6000", "department": "Facilities"},
            {"code": "6030", "name": "Utilities Expense", "type": "EXPENSE", "subtype": "OPERATING_EXPENSE", "normal": "DEBIT", "description": "Electricity, internet, and utilities", "parent": "6000", "department": "Facilities"},
            {"code": "6040", "name": "Bank Fees", "type": "EXPENSE", "subtype": "OTHER_EXPENSE", "normal": "DEBIT", "description": "Bank service charges", "parent": "6000", "department": "Finance"},
            {"code": "6050", "name": "Depreciation Expense", "type": "EXPENSE", "subtype": "OPERATING_EXPENSE", "normal": "DEBIT", "description": "Monthly depreciation expense", "parent": "6000", "department": "Finance"},
        ]

        accounts: dict[str, object] = {}
        for row in account_rows:
            parent = accounts.get(row["parent"])
            account, _created = account_model.objects.get_or_create(
                account_code=row["code"],
                defaults={
                    "account_name": row["name"],
                    "account_type": row["type"],
                    "account_subtype": row["subtype"],
                    "parent_account": parent,
                    "is_active": True,
                    "is_system_account": row["code"] in {"1100", "2010", "2030"},
                    "description": row["description"],
                    "normal_balance": row["normal"],
                    "currency": "USD",
                    "opening_balance": Decimal("0"),
                    "allow_manual_posting": row["code"] not in {"1100", "2010", "2030"},
                    "requires_reconciliation": row.get("reconcile", False),
                    "tax_code": row.get("tax"),
                    "bank_account": bank_accounts.get(row.get("bank")),
                },
            )
            accounts[row["code"]] = account

        period_objects: dict[str, object] = {}
        period_rows = []
        for year in (current_year - 1, current_year):
            for month in range(1, 13):
                period_code = f"FY{year}-{month:02d}"
                closed = year < current_year or month < current_month
                period_rows.append(
                    {
                        "period_code": period_code,
                        "period_name": date(year, month, 1).strftime("%B %Y"),
                        "fiscal_year": year,
                        "period_number": month,
                        "quarter": ((month - 1) // 3) + 1,
                        "start_date": date(year, month, 1),
                        "end_date": self._finance_month_end(year, month),
                        "status": "CLOSED" if closed else "OPEN",
                        "is_adjusting_period": False,
                        "is_year_end": month == 12,
                        "closed_by": ledger_user if closed else None,
                        "closed_date": posting_timestamp if closed else None,
                        "notes": "Closed historical period." if closed else "Open reporting period for test transactions.",
                    }
                )
        for row in period_rows:
            period, _created = fiscal_period_model.objects.get_or_create(
                period_code=row["period_code"],
                defaults={key: value for key, value in row.items() if key != "period_code"},
            )
            period_objects[row["period_code"]] = period

        journal_rows = [
            {"code": "GJ", "name": "General Journal", "type": "GENERAL", "prefix": "GJ", "approval": False, "notes": "Opening entries and non-routine postings."},
            {"code": "SJ", "name": "Sales Journal", "type": "SALES", "prefix": "SI", "approval": True, "notes": "Customer invoices and sales adjustments."},
            {"code": "PJ", "name": "Purchase Journal", "type": "PURCHASE", "prefix": "PI", "approval": True, "notes": "Vendor invoices and inventory purchases."},
            {"code": "CRJ", "name": "Cash Receipts Journal", "type": "CASH_RECEIPTS", "prefix": "CR", "approval": False, "notes": "Customer receipts and other deposits."},
            {"code": "CDJ", "name": "Cash Disbursements Journal", "type": "CASH_DISBURSEMENTS", "prefix": "CD", "approval": True, "notes": "Supplier, payroll, and operating payments."},
            {"code": "PRJ", "name": "Payroll Journal", "type": "PAYROLL", "prefix": "PR", "approval": True, "notes": "Monthly payroll and payroll tax accruals."},
            {"code": "AJ", "name": "Adjusting Journal", "type": "ADJUSTING", "prefix": "AJ", "approval": True, "notes": "Depreciation, accruals, and period-end adjustments."},
        ]
        journals: dict[str, object] = {}
        for row in journal_rows:
            journal, _created = journal_model.objects.get_or_create(
                journal_code=row["code"],
                defaults={
                    "journal_name": row["name"],
                    "journal_type": row["type"],
                    "description": row["notes"],
                    "is_active": True,
                    "auto_numbering": True,
                    "next_entry_number": 1,
                    "requires_approval": row["approval"],
                    "sequence_prefix": row["prefix"],
                    "default_currency": "USD",
                    "notes": row["notes"],
                },
            )
            journals[row["code"]] = journal

        def finance_line(
            account_code: str,
            description: str,
            debit: Decimal = Decimal("0"),
            credit: Decimal = Decimal("0"),
            quantity: Decimal = Decimal("1"),
            unit_price: Decimal = Decimal("0"),
            tax_rate: Decimal = Decimal("0"),
            tax_amount: Decimal = Decimal("0"),
            tax_code: str | None = None,
            cost_center: str | None = None,
            project_code: str | None = None,
            department: str | None = None,
            reference_number: str | None = None,
            due_date: date | None = None,
        ) -> dict[str, object]:
            return {
                "account_code": account_code,
                "description": description,
                "debit": debit,
                "credit": credit,
                "quantity": quantity,
                "unit_price": unit_price,
                "tax_rate": tax_rate,
                "tax_amount": tax_amount,
                "tax_code": tax_code,
                "cost_center": cost_center,
                "project_code": project_code,
                "department": department,
                "reference_number": reference_number,
                "due_date": due_date,
            }

        entry_specs: list[dict[str, object]] = []
        ar_invoice_specs: list[dict[str, object]] = []
        ar_receipt_specs: list[dict[str, object]] = []
        ap_invoice_specs: list[dict[str, object]] = []
        ap_payment_specs: list[dict[str, object]] = []

        def add_entry(
            journal_code: str,
            entry_number: str,
            entry_date: date,
            description: str,
            lines: list[dict[str, object]],
            source_type: str,
            source_id: str,
            reference_number: str | None = None,
            due_date: date | None = None,
            recurring: bool = False,
        ) -> None:
            entry_specs.append(
                {
                    "journal_code": journal_code,
                    "entry_number": entry_number,
                    "entry_date": entry_date,
                    "description": description,
                    "lines": lines,
                    "source_type": source_type,
                    "source_id": source_id,
                    "reference_number": reference_number,
                    "due_date": due_date,
                    "recurring": recurring,
                }
            )

        opening_date = self._finance_transaction_date(current_year, 1, 2)
        add_entry(
            "GJ",
            f"GJ-{current_year}-0001",
            opening_date,
            "Opening capitalization and cash funding",
            [
                finance_line("1010", "Opening operating cash", debit=Decimal("90000.00"), reference_number="OPENING"),
                finance_line("1020", "Opening reserve cash", debit=Decimal("20000.00"), reference_number="OPENING"),
                finance_line("3010", "Common stock issued for initial funding", credit=Decimal("110000.00"), reference_number="OPENING"),
            ],
            "OTHER",
            f"OPENING-{current_year}",
            reference_number=f"OPENING-{current_year}",
        )
        equipment_date = self._finance_transaction_date(current_year, 1, 8)
        add_entry(
            "CDJ",
            f"CD-{current_year}-0001",
            equipment_date,
            "Purchase of production and office computer equipment",
            [
                finance_line("1510", "New laptops and warehouse scanners", debit=Decimal("18000.00"), quantity=12, unit_price=Decimal("1500.00"), cost_center="IT-001", reference_number="PO-2026-0001"),
                finance_line("1010", "Payment for computer equipment", credit=Decimal("18000.00"), cost_center="IT-001", reference_number="PO-2026-0001"),
            ],
            "PAYMENT",
            f"PO-2026-0001",
            reference_number="PO-2026-0001",
        )

        for month in range(1, current_month + 1):
            month_tag = f"{current_year}-{month:02d}"
            invoice_date = self._finance_transaction_date(current_year, month, 5)
            receipt_date = self._finance_transaction_date(current_year, month, 18)
            bill_date = self._finance_transaction_date(current_year, month, 7)
            payment_date = self._finance_transaction_date(current_year, month, 24)
            due_date = invoice_date + timedelta(days=30)
            bill_due_date = bill_date + timedelta(days=30)

            sales_subtotal = (Decimal("9000.00") + Decimal(month * 350)).quantize(Decimal("0.01"))
            sales_tax = (sales_subtotal * Decimal("0.08")).quantize(Decimal("0.01"))
            sales_total = sales_subtotal + sales_tax
            invoice_number = f"INV-{month_tag}-001"
            ar_invoice_specs.append(
                {
                    "invoice_number": invoice_number,
                    "customer_code": ["CUST-ACME", "CUST-NOVA", "CUST-GREEN"][month % 3],
                    "date": invoice_date,
                    "due_date": due_date,
                    "subtotal": sales_subtotal,
                    "tax": sales_tax,
                    "total": sales_total,
                    "paid": sales_total if month in {1, 2, 4} else (sales_total * Decimal("0.45")).quantize(Decimal("0.01")),
                    "source_id": invoice_number,
                }
            )
            add_entry(
                "SJ",
                f"SI-{month_tag}-001",
                invoice_date,
                f"Product sale invoiced to customer ({invoice_number})",
                [
                    finance_line("1100", "Customer receivable including sales tax", debit=sales_total, tax_amount=sales_tax, tax_code="SALES-8", project_code=f"PRJ-{month:02d}", reference_number=invoice_number, due_date=due_date),
                    finance_line("4010", "Product sales revenue", credit=sales_subtotal, quantity=Decimal("100"), unit_price=(sales_subtotal / Decimal("100")).quantize(Decimal("0.01")), project_code=f"PRJ-{month:02d}", reference_number=invoice_number),
                    finance_line("2030", "Sales tax collected", credit=sales_tax, tax_amount=sales_tax, tax_code="SALES-8", reference_number=invoice_number),
                ],
                "INVOICE",
                invoice_number,
                reference_number=invoice_number,
                due_date=due_date,
            )

            cogs_amount = (sales_subtotal * Decimal("0.43")).quantize(Decimal("0.01"))
            add_entry(
                "GJ",
                f"GJ-{month_tag}-COGS",
                self._finance_transaction_date(current_year, month, 6),
                f"Recognize cost of goods sold for {invoice_number}",
                [
                    finance_line("5000", "Cost of products shipped", debit=cogs_amount, quantity=Decimal("100"), unit_price=(cogs_amount / Decimal("100")).quantize(Decimal("0.01")), project_code=f"PRJ-{month:02d}", reference_number=invoice_number),
                    finance_line("1200", "Inventory relieved for shipment", credit=cogs_amount, project_code=f"PRJ-{month:02d}", reference_number=invoice_number),
                ],
                "OTHER",
                f"COGS-{month_tag}",
                reference_number=invoice_number,
            )

            receipt_amount = ar_invoice_specs[-1]["paid"]
            receipt_number = f"RCT-{month_tag}-001"
            ar_receipt_specs.append(
                {
                    "receipt_number": receipt_number,
                    "customer_code": ar_invoice_specs[-1]["customer_code"],
                    "date": receipt_date,
                    "amount": receipt_amount,
                    "invoice_number": invoice_number,
                    "source_id": receipt_number,
                }
            )
            add_entry(
                "CRJ",
                f"CR-{month_tag}-001",
                receipt_date,
                f"Customer receipt applied to {invoice_number}",
                [
                    finance_line("1010", "Deposit from customer", debit=receipt_amount, reference_number=receipt_number),
                    finance_line("1100", "Apply receipt against customer receivable", credit=receipt_amount, reference_number=invoice_number),
                ],
                "RECEIPT",
                receipt_number,
                reference_number=receipt_number,
            )

            purchase_subtotal = (Decimal("4200.00") + Decimal(month * 210)).quantize(Decimal("0.01"))
            purchase_tax = (purchase_subtotal * Decimal("0.08")).quantize(Decimal("0.01"))
            purchase_total = purchase_subtotal + purchase_tax
            vendor_invoice_number = f"BILL-{month_tag}-001"
            ap_invoice_specs.append(
                {
                    "invoice_number": vendor_invoice_number,
                    "vendor_code": ["VEND-ATLAS", "VEND-CLEAR", "VEND-CLOUD"][month % 3],
                    "date": bill_date,
                    "due_date": bill_due_date,
                    "subtotal": purchase_subtotal,
                    "tax": purchase_tax,
                    "total": purchase_total,
                    "paid": purchase_total if month % 3 == 0 else (purchase_total * Decimal("0.55")).quantize(Decimal("0.01")),
                    "source_id": vendor_invoice_number,
                }
            )
            add_entry(
                "PJ",
                f"PI-{month_tag}-001",
                bill_date,
                f"Inventory purchase from vendor ({vendor_invoice_number})",
                [
                    finance_line("1200", "Purchased components and finished goods", debit=purchase_subtotal, quantity=Decimal("120"), unit_price=(purchase_subtotal / Decimal("120")).quantize(Decimal("0.01")), reference_number=vendor_invoice_number, due_date=bill_due_date),
                    finance_line("1400", "Recoverable tax on supplier invoice", debit=purchase_tax, tax_amount=purchase_tax, tax_code="PURCHASE-8", reference_number=vendor_invoice_number),
                    finance_line("2010", "Vendor payable including tax", credit=purchase_total, tax_amount=purchase_tax, tax_code="PURCHASE-8", reference_number=vendor_invoice_number, due_date=bill_due_date),
                ],
                "INVOICE",
                vendor_invoice_number,
                reference_number=vendor_invoice_number,
                due_date=bill_due_date,
            )

            vendor_payment_amount = ap_invoice_specs[-1]["paid"]
            payment_number = f"VPMT-{month_tag}-001"
            ap_payment_specs.append(
                {
                    "payment_number": payment_number,
                    "vendor_code": ap_invoice_specs[-1]["vendor_code"],
                    "date": payment_date,
                    "amount": vendor_payment_amount,
                    "invoice_number": vendor_invoice_number,
                    "source_id": payment_number,
                }
            )
            add_entry(
                "CDJ",
                f"CD-{month_tag}-001",
                payment_date,
                f"Vendor payment applied to {vendor_invoice_number}",
                [
                    finance_line("2010", "Reduce vendor payable", debit=vendor_payment_amount, reference_number=vendor_invoice_number),
                    finance_line("1010", "Payment from operating account", credit=vendor_payment_amount, reference_number=payment_number),
                ],
                "PAYMENT",
                payment_number,
                reference_number=payment_number,
            )

            gross_pay = (Decimal("14500.00") + Decimal(month * 175)).quantize(Decimal("0.01"))
            payroll_tax = (gross_pay * Decimal("0.21")).quantize(Decimal("0.01"))
            net_pay = gross_pay - payroll_tax
            add_entry(
                "PRJ",
                f"PR-{month_tag}-001",
                self._finance_transaction_date(current_year, month, 25),
                f"Monthly payroll accrual for {date(current_year, month, 1).strftime('%B %Y')}",
                [
                    finance_line("6010", "Gross payroll expense", debit=gross_pay, cost_center="HR-001", department="People Operations", reference_number=f"PAYROLL-{month_tag}"),
                    finance_line("1010", "Net payroll paid", credit=net_pay, cost_center="HR-001", department="People Operations", reference_number=f"PAYROLL-{month_tag}"),
                    finance_line("2020", "Payroll taxes withheld", credit=payroll_tax, cost_center="HR-001", department="People Operations", reference_number=f"PAYROLL-{month_tag}"),
                ],
                "PAYMENT",
                f"PAYROLL-{month_tag}",
                reference_number=f"PAYROLL-{month_tag}",
                recurring=True,
            )

            rent_amount = Decimal("4000.00")
            add_entry(
                "CDJ",
                f"CD-{month_tag}-RENT",
                self._finance_transaction_date(current_year, month, 3),
                f"Monthly office and warehouse rent for {month_tag}",
                [
                    finance_line("6020", "Office and warehouse rent", debit=rent_amount, cost_center="FAC-001", department="Facilities", reference_number=f"LEASE-{current_year}"),
                    finance_line("1010", "Rent payment", credit=rent_amount, cost_center="FAC-001", department="Facilities", reference_number=f"LEASE-{current_year}"),
                ],
                "PAYMENT",
                f"RENT-{month_tag}",
                reference_number=f"LEASE-{current_year}",
                recurring=True,
            )

            utility_amount = (Decimal("520.00") + Decimal(month * 40)).quantize(Decimal("0.01"))
            add_entry(
                "PJ",
                f"PI-{month_tag}-UTIL",
                self._finance_transaction_date(current_year, month, 12),
                f"Utilities accrual for {month_tag}",
                [
                    finance_line("6030", "Electricity, internet, and utilities", debit=utility_amount, cost_center="FAC-001", department="Facilities", reference_number=f"UTIL-{month_tag}"),
                    finance_line("2010", "Utilities payable", credit=utility_amount, cost_center="FAC-001", department="Facilities", reference_number=f"UTIL-{month_tag}"),
                ],
                "OTHER",
                f"UTIL-{month_tag}",
                reference_number=f"UTIL-{month_tag}",
                recurring=True,
            )

            depreciation_amount = Decimal("650.00")
            add_entry(
                "AJ",
                f"AJ-{month_tag}-DEP",
                self._finance_transaction_date(current_year, month, 28),
                f"Monthly depreciation for {month_tag}",
                [
                    finance_line("6050", "Depreciation expense", debit=depreciation_amount, cost_center="FIN-001", department="Finance", reference_number=f"DEP-{current_year}"),
                    finance_line("1520", "Accumulated depreciation", credit=depreciation_amount, cost_center="FIN-001", department="Finance", reference_number=f"DEP-{current_year}"),
                ],
                "ADJUSTMENT",
                f"DEP-{month_tag}",
                reference_number=f"DEP-{current_year}",
                recurring=True,
            )

            if month % 2 == 0:
                bank_fee = Decimal("45.00")
                add_entry(
                    "CDJ",
                    f"CD-{month_tag}-FEE",
                    self._finance_transaction_date(current_year, month, 27),
                    f"Bank service charges for {month_tag}",
                    [
                        finance_line("6040", "Monthly bank fees", debit=bank_fee, cost_center="FIN-001", department="Finance", reference_number=f"BANK-{month_tag}"),
                        finance_line("1010", "Bank fees paid", credit=bank_fee, cost_center="FIN-001", department="Finance", reference_number=f"BANK-{month_tag}"),
                    ],
                    "PAYMENT",
                    f"BANK-{month_tag}",
                    reference_number=f"BANK-{month_tag}",
                    recurring=True,
                )

        if current_month >= 3:
            transfer_amount = Decimal("5000.00")
            add_entry(
                "GJ",
                f"GJ-{current_year}-RESERVE",
                self._finance_transaction_date(current_year, 3, 29),
                "Transfer excess operating cash to reserve savings",
                [
                    finance_line("1020", "Transfer into reserve savings", debit=transfer_amount, reference_number=f"XFER-{current_year}-Q1"),
                    finance_line("1010", "Transfer from operating checking", credit=transfer_amount, reference_number=f"XFER-{current_year}-Q1"),
                ],
                "TRANSFER",
                f"XFER-{current_year}-Q1",
                reference_number=f"XFER-{current_year}-Q1",
            )

        if current_month >= 6:
            prepaid_amount = Decimal("3600.00")
            add_entry(
                "AJ",
                f"AJ-{current_year}-PREPAID",
                self._finance_transaction_date(current_year, 6, 30),
                "Annual insurance premium paid in advance",
                [
                    finance_line("1300", "Prepaid insurance", debit=prepaid_amount, cost_center="FIN-001", department="Finance", reference_number=f"INS-{current_year}"),
                    finance_line("1010", "Insurance premium paid", credit=prepaid_amount, cost_center="FIN-001", department="Finance", reference_number=f"INS-{current_year}"),
                ],
                "ADJUSTMENT",
                f"INS-{current_year}",
                reference_number=f"INS-{current_year}",
            )

        entry_by_source: dict[str, object] = {}
        activity: dict[tuple[str, str], dict[str, Decimal]] = {}
        running_balances = {code: Decimal("0") for code in accounts}
        line_by_source: dict[str, object] = {}
        for spec in sorted(entry_specs, key=lambda item: (item["entry_date"], item["entry_number"])):
            journal = journals[spec["journal_code"]]
            entry_defaults = {
                "reference_number": spec["reference_number"],
                "entry_date": spec["entry_date"],
                "document_date": spec["entry_date"],
                "posting_date": spec["entry_date"],
                "description": spec["description"],
                "total_debit": sum(line["debit"] for line in spec["lines"]),
                "total_credit": sum(line["credit"] for line in spec["lines"]),
                "currency": "USD",
                "exchange_rate": Decimal("1"),
                "due_date": spec["due_date"],
                "status": "POSTED",
                "approved_by": ledger_user,
                "approved_date": posting_timestamp,
                "posted_by": ledger_user,
                "posted_date": posting_timestamp,
                "source_document_type": spec["source_type"],
                "source_document_id": spec["source_id"],
                "source_system": "seed-fixture",
                "is_recurring": spec["recurring"],
                "recurrence_key": spec["source_id"] if spec["recurring"] else None,
                "notes": "Generated by create_test_data for finance reporting demos.",
            }
            entry, _created = journal_entry_model.objects.get_or_create(
                journal=journal,
                entry_number=spec["entry_number"],
                defaults=entry_defaults,
            )
            entry_by_source[spec["source_id"]] = entry
            for line_number, line in enumerate(spec["lines"], start=1):
                account = accounts[line["account_code"]]
                period_code = f"FY{spec['entry_date'].year}-{spec['entry_date'].month:02d}"
                activity_key = (line["account_code"], period_code)
                activity.setdefault(activity_key, {"debit": Decimal("0"), "credit": Decimal("0")})
                activity[activity_key]["debit"] += line["debit"]
                activity[activity_key]["credit"] += line["credit"]
                running_balances[line["account_code"]] += line["debit"] - line["credit"]
                line_defaults = {
                    "account": account,
                    "description": line["description"],
                    "debit_amount": line["debit"],
                    "credit_amount": line["credit"],
                    "currency": "USD",
                    "exchange_rate": Decimal("1"),
                    "quantity": line["quantity"],
                    "unit_price": line["unit_price"],
                    "tax_rate": line["tax_rate"],
                    "tax_code": line["tax_code"],
                    "tax_amount": line["tax_amount"],
                    "cost_center": line["cost_center"],
                    "project_code": line["project_code"],
                    "department": line["department"],
                    "reference_number": line["reference_number"],
                    "due_date": line["due_date"],
                }
                entry_line, _created = journal_entry_line_model.objects.get_or_create(
                    journal_entry=entry,
                    line_number=line_number,
                    defaults=line_defaults,
                )
                if spec["source_type"] in {"INVOICE", "RECEIPT", "PAYMENT"} and spec["source_id"] not in line_by_source:
                    line_by_source[spec["source_id"]] = entry_line
                transaction_defaults = {
                    "account": account,
                    "fiscal_period": period_objects[period_code],
                    "transaction_date": spec["entry_date"],
                    "posting_date": spec["entry_date"],
                    "description": line["description"],
                    "debit_amount": line["debit"],
                    "credit_amount": line["credit"],
                    "running_balance": running_balances[line["account_code"]],
                    "currency": "USD",
                    "exchange_rate": Decimal("1"),
                    "transaction_type": "DEBIT" if line["debit"] else "CREDIT",
                    "batch_number": spec["source_id"],
                    "line_number": line_number,
                    "is_reconciled": line["account_code"] in {"1010", "1020"} and spec["entry_date"] < today - timedelta(days=30),
                    "reconciliation_date": today - timedelta(days=5) if line["account_code"] in {"1010", "1020"} and spec["entry_date"] < today - timedelta(days=30) else None,
                    "reference_number": line["reference_number"],
                    "cost_center": line["cost_center"],
                    "project_code": line["project_code"],
                    "department": line["department"],
                }
                gl_transaction_model.objects.get_or_create(
                    journal_entry_line=entry_line,
                    defaults=transaction_defaults,
                )

        if account_balance_model:
            for account_code, account in accounts.items():
                running_balance = Decimal("0")
                ytd_debit = Decimal("0")
                ytd_credit = Decimal("0")
                for period_row in period_rows:
                    period_code = period_row["period_code"]
                    values = activity.get((account_code, period_code), {"debit": Decimal("0"), "credit": Decimal("0")})
                    if period_row["fiscal_year"] == current_year:
                        ytd_debit += values["debit"]
                        ytd_credit += values["credit"]
                    opening_balance = running_balance
                    net_change = values["debit"] - values["credit"]
                    running_balance += net_change
                    account_balance_model.objects.get_or_create(
                        account=account,
                        fiscal_period=period_objects[period_code],
                        defaults={
                            "opening_balance": opening_balance,
                            "debit_total": values["debit"],
                            "credit_total": values["credit"],
                            "closing_balance": running_balance,
                            "currency": "USD",
                            "net_change": net_change,
                            "year_to_date_debit": ytd_debit if period_row["fiscal_year"] == current_year else Decimal("0"),
                            "year_to_date_credit": ytd_credit if period_row["fiscal_year"] == current_year else Decimal("0"),
                            "year_to_date_balance": (ytd_debit - ytd_credit) if period_row["fiscal_year"] == current_year else Decimal("0"),
                            "as_of_date": min(period_row["end_date"], today),
                            "is_locked": period_row["status"] in {"CLOSED", "LOCKED"},
                        },
                    )

        if budget_model:
            budget_templates = {
                "4010": Decimal("21000.00"),
                "5000": Decimal("9500.00"),
                "6010": Decimal("18000.00"),
                "6020": Decimal("4000.00"),
                "6030": Decimal("1500.00"),
                "6040": Decimal("250.00"),
                "6050": Decimal("700.00"),
            }
            for month in range(1, 13):
                period_code = f"FY{current_year}-{month:02d}"
                for account_code, budgeted_amount in budget_templates.items():
                    actual_values = activity.get((account_code, period_code), {"debit": Decimal("0"), "credit": Decimal("0")})
                    actual_amount = actual_values["credit"] if account_code == "4010" else actual_values["debit"]
                    variance_amount = actual_amount - budgeted_amount if account_code == "4010" else budgeted_amount - actual_amount
                    variance_percentage = (variance_amount / budgeted_amount * Decimal("100")).quantize(Decimal("0.01")) if budgeted_amount else Decimal("0")
                    forecast_amount = actual_amount if month <= current_month and actual_amount else budgeted_amount
                    committed_amount = (budgeted_amount * Decimal("0.15")).quantize(Decimal("0.01")) if account_code != "4010" else Decimal("0")
                    budget_code = f"BUD-{current_year}-{month:02d}-{account_code}"
                    budget_model.objects.get_or_create(
                        budget_code=budget_code,
                        defaults={
                            "budget_name": f"{current_year} monthly budget - {accounts[account_code].account_name}",
                            "budget_version": f"{current_year}-BASE",
                            "account": accounts[account_code],
                            "fiscal_period": period_objects[period_code],
                            "budget_type": "OPERATING" if account_code not in {"4010", "5000"} else "MASTER",
                            "budgeted_amount": budgeted_amount,
                            "actual_amount": actual_amount,
                            "variance_amount": variance_amount,
                            "variance_percentage": variance_percentage,
                            "forecast_amount": forecast_amount,
                            "committed_amount": committed_amount,
                            "currency": "USD",
                            "department": "Sales" if account_code == "4010" else "Finance" if account_code in {"6040", "6050"} else "Operations",
                            "cost_center": "SALES-001" if account_code == "4010" else "OPS-001",
                            "status": "ACTIVE" if month <= current_month else "APPROVED",
                            "notes": "Seeded monthly budget for dashboard and variance reporting.",
                        },
                    )

        self._create_accounts_receivable_payable_data(
            account_objects=accounts,
            bank_accounts=bank_accounts,
            entry_by_source=entry_by_source,
            ar_invoice_specs=ar_invoice_specs,
            ar_receipt_specs=ar_receipt_specs,
            ap_invoice_specs=ap_invoice_specs,
            ap_payment_specs=ap_payment_specs,
            crm_account_model=self._get_model("CrmAccount"),
        )

    def _create_accounts_receivable_payable_data(
        self,
        account_objects: dict[str, object],
        bank_accounts: dict[str, object],
        entry_by_source: dict[str, object],
        ar_invoice_specs: list[dict[str, object]],
        ar_receipt_specs: list[dict[str, object]],
        ap_invoice_specs: list[dict[str, object]],
        ap_payment_specs: list[dict[str, object]],
        crm_account_model,
    ) -> None:
        customer_model = self._get_model("Customer")
        customer_invoice_model = self._get_model("CustomerInvoice")
        customer_invoice_line_model = self._get_model("CustomerInvoiceLine")
        customer_receipt_model = self._get_model("CustomerReceipt")
        vendor_model = self._get_model("Vendor")
        vendor_invoice_model = self._get_model("VendorInvoice")
        vendor_invoice_line_model = self._get_model("VendorInvoiceLine")
        vendor_payment_model = self._get_model("VendorPayment")

        crm_accounts = {}
        if crm_account_model:
            crm_accounts = {
                obj.account_name: obj
                for obj in crm_account_model.objects.filter(
                    account_name__in=["Acme Manufacturing", "Nova Retailers"]
                )
            }

        customers: dict[str, object] = {}
        if customer_model:
            customer_rows = [
                {"code": "CUST-ACME", "name": "Acme Manufacturing", "crm": crm_accounts.get("Acme Manufacturing"), "email": "ap@acme.example.com", "phone": "+1-555-0100", "terms": 30, "limit": Decimal("75000.00"), "tax": "US-ACME-8842"},
                {"code": "CUST-NOVA", "name": "Nova Retailers", "crm": crm_accounts.get("Nova Retailers"), "email": "finance@nova.example.com", "phone": "+1-555-0200", "terms": 45, "limit": Decimal("50000.00"), "tax": "US-NOVA-2194"},
                {"code": "CUST-GREEN", "name": "Greenline Distribution", "crm": None, "email": "billing@greenline.example.com", "phone": "+1-555-0300", "terms": 30, "limit": Decimal("35000.00"), "tax": "US-GREEN-7731"},
            ]
            for row in customer_rows:
                customer, _created = customer_model.objects.get_or_create(
                    customer_code=row["code"],
                    defaults={
                        "customer_name": row["name"],
                        "crm_account": row["crm"],
                        "email": row["email"],
                        "phone": row["phone"],
                        "billing_address": f"{row['name']} Finance Department, Springfield",
                        "currency": "USD",
                        "payment_terms_days": row["terms"],
                        "credit_limit": row["limit"],
                        "tax_number": row["tax"],
                        "status": "ACTIVE",
                        "is_active": True,
                        "notes": "Seed customer for receivables, aging, and collection demos.",
                    },
                )
                customers[row["code"]] = customer

        if customer_invoice_model and customers:
            for spec in ar_invoice_specs:
                invoice, _created = customer_invoice_model.objects.get_or_create(
                    invoice_number=spec["invoice_number"],
                    defaults={
                        "customer": customers[spec["customer_code"]],
                        "journal_entry": entry_by_source.get(spec["source_id"]),
                        "invoice_date": spec["date"],
                        "due_date": spec["due_date"],
                        "currency": "USD",
                        "exchange_rate": Decimal("1"),
                        "subtotal": spec["subtotal"],
                        "tax_amount": spec["tax"],
                        "total_amount": spec["total"],
                        "paid_amount": spec["paid"],
                        "outstanding_amount": spec["total"] - spec["paid"],
                        "status": "PAID" if spec["paid"] == spec["total"] else "PARTIALLY_PAID",
                        "sales_order_number": f"SO-{spec['invoice_number'][4:]}",
                        "customer_reference": f"PO-{spec['invoice_number'][4:]}" ,
                        "notes": "Seed invoice generated from the sales journal.",
                    },
                )
                if customer_invoice_line_model:
                    first_line = (spec["subtotal"] * Decimal("0.60")).quantize(Decimal("0.01"))
                    second_line = spec["subtotal"] - first_line
                    for line_number, amount, description, product_code in [
                        (1, first_line, "Standard production widgets", "PROD-100"),
                        (2, second_line, "Implementation and configuration services", "SERV-200"),
                    ]:
                        tax_amount = (amount * Decimal("0.08")).quantize(Decimal("0.01"))
                        customer_invoice_line_model.objects.get_or_create(
                            invoice=invoice,
                            line_number=line_number,
                            defaults={
                                "product_code": product_code,
                                "description": description,
                                "quantity": Decimal("50") if line_number == 1 else Decimal("1"),
                                "unit_price": (amount / (Decimal("50") if line_number == 1 else Decimal("1"))).quantize(Decimal("0.01")),
                                "tax_rate": Decimal("0.08"),
                                "tax_amount": tax_amount,
                                "line_total": amount + tax_amount,
                                "revenue_account": account_objects["4010"] if line_number == 1 else account_objects["4020"],
                            },
                        )

        if customer_receipt_model and customers:
            for spec in ar_receipt_specs:
                customer_receipt_model.objects.get_or_create(
                    receipt_number=spec["receipt_number"],
                    defaults={
                        "customer": customers[spec["customer_code"]],
                        "bank_account": bank_accounts["111222333"],
                        "journal_entry": entry_by_source.get(spec["source_id"]),
                        "receipt_date": spec["date"],
                        "amount": spec["amount"],
                        "currency": "USD",
                        "payment_method": "ACH" if spec["customer_code"] != "CUST-NOVA" else "WIRE",
                        "reference_number": f"ACH-{spec['receipt_number'][4:]}",
                        "status": "POSTED",
                        "notes": f"Applied against {spec['invoice_number']}.",
                    },
                )

        vendors: dict[str, object] = {}
        if vendor_model:
            vendor_rows = [
                {"code": "VEND-ATLAS", "name": "Atlas Components LLC", "email": "invoices@atlas.example.com", "phone": "+1-555-0400", "terms": 30, "tax": "US-ATLAS-4410"},
                {"code": "VEND-CLEAR", "name": "Clearwater Utilities", "email": "billing@clearwater.example.com", "phone": "+1-555-0500", "terms": 15, "tax": "US-CLEAR-5521"},
                {"code": "VEND-CLOUD", "name": "CloudNine Software", "email": "accounts@cloudnine.example.com", "phone": "+1-555-0600", "terms": 30, "tax": "US-CLOUD-6632"},
            ]
            for row in vendor_rows:
                vendor, _created = vendor_model.objects.get_or_create(
                    vendor_code=row["code"],
                    defaults={
                        "vendor_name": row["name"],
                        "email": row["email"],
                        "phone": row["phone"],
                        "address": f"{row['name']} Accounts Payable, Springfield",
                        "currency": "USD",
                        "payment_terms_days": row["terms"],
                        "tax_number": row["tax"],
                        "status": "ACTIVE",
                        "is_active": True,
                        "notes": "Seed vendor for payables, aging, and payment workflow demos.",
                    },
                )
                vendors[row["code"]] = vendor

        if vendor_invoice_model and vendors:
            for spec in ap_invoice_specs:
                invoice, _created = vendor_invoice_model.objects.get_or_create(
                    invoice_number=spec["invoice_number"],
                    defaults={
                        "vendor": vendors[spec["vendor_code"]],
                        "journal_entry": entry_by_source.get(spec["source_id"]),
                        "invoice_date": spec["date"],
                        "due_date": spec["due_date"],
                        "currency": "USD",
                        "exchange_rate": Decimal("1"),
                        "subtotal": spec["subtotal"],
                        "tax_amount": spec["tax"],
                        "total_amount": spec["total"],
                        "paid_amount": spec["paid"],
                        "outstanding_amount": spec["total"] - spec["paid"],
                        "status": "PAID" if spec["paid"] == spec["total"] else "PARTIALLY_PAID",
                        "purchase_order_number": f"PO-{spec['invoice_number'][5:]}" ,
                        "vendor_reference": f"{spec['vendor_code']}-{spec['invoice_number']}",
                        "notes": "Seed invoice generated from the purchase journal.",
                    },
                )
                if vendor_invoice_line_model:
                    vendor_invoice_line_model.objects.get_or_create(
                        invoice=invoice,
                        line_number=1,
                        defaults={
                            "item_code": "COMP-100",
                            "description": "Production components and replenishment stock",
                            "quantity": Decimal("120"),
                            "unit_price": (spec["subtotal"] / Decimal("120")).quantize(Decimal("0.01")),
                            "tax_rate": Decimal("0.08"),
                            "tax_amount": spec["tax"],
                            "line_total": spec["total"],
                            "expense_account": account_objects["1200"],
                        },
                    )

        if vendor_payment_model and vendors:
            for spec in ap_payment_specs:
                vendor_payment_model.objects.get_or_create(
                    payment_number=spec["payment_number"],
                    defaults={
                        "vendor": vendors[spec["vendor_code"]],
                        "bank_account": bank_accounts["111222333"],
                        "journal_entry": entry_by_source.get(spec["source_id"]),
                        "payment_date": spec["date"],
                        "amount": spec["amount"],
                        "currency": "USD",
                        "payment_method": "ACH" if spec["vendor_code"] != "VEND-CLOUD" else "CARD",
                        "reference_number": f"PAY-{spec['payment_number'][5:]}",
                        "status": "PAID",
                        "notes": f"Applied against {spec['invoice_number']}.",
                    },
                )

    @staticmethod
    def _finance_month_end(year: int, month: int) -> date:
        if month == 12:
            return date(year, 12, 31)
        return date(year, month + 1, 1) - timedelta(days=1)

    @staticmethod
    def _finance_transaction_date(year: int, month: int, day: int) -> date:
        today = date.today()
        safe_day = min(day, Command._finance_month_end(year, month).day)
        if year == today.year and month == today.month:
            safe_day = min(safe_day, today.day)
        return date(year, month, safe_day)

    def _create_crm_data(self, force: bool) -> None:
        account_model = self._get_model("CrmAccount")
        contact_model = self._get_model("Contact")
        stage_model = self._get_model("OpportunityStage")
        lead_model = self._get_model("Lead")
        opportunity_model = self._get_model("Opportunity")
        activity_model = self._get_model("Activity")

        if not self._should_create(account_model, force):
            self.stdout.write("Skipping CRM data (already exists).")
            return

        accounts = self._create_records(
            account_model,
            [
                {
                    "account_name": "Acme Manufacturing",
                    "account_type": "customer",
                    "industry": "Manufacturing",
                    "website": "https://acme.example.com",
                    "primary_email": "info@acme.example.com",
                    "primary_phone": "+1-555-0100",
                    "billing_address": "123 Industrial Way, Springfield",
                    "shipping_address": "Warehouse District, Springfield",
                    "rating": "hot",
                    "is_active": True,
                },
                {
                    "account_name": "Nova Retailers",
                    "account_type": "prospect",
                    "industry": "Retail",
                    "website": "https://nova.example.com",
                    "primary_email": "hello@nova.example.com",
                    "primary_phone": "+1-555-0200",
                    "billing_address": "456 Market St, Springfield",
                    "shipping_address": "456 Market St, Springfield",
                    "rating": "warm",
                    "is_active": True,
                },
            ],
            ["account_name"],
        )

        contacts = []
        if contact_model and accounts:
            contacts = self._create_records(
                contact_model,
                [
                    {
                        "account": accounts[0],
                        "first_name": "Riley",
                        "last_name": "Chen",
                        "title": "Procurement Manager",
                        "department": "Purchasing",
                        "email": "riley.chen@acme.example.com",
                        "phone": "+1-555-0110",
                        "mobile_phone": "+1-555-0111",
                        "is_primary": True,
                        "notes": "Prefers email follow-ups.",
                    },
                    {
                        "account": accounts[1],
                        "first_name": "Morgan",
                        "last_name": "Lee",
                        "title": "Operations Lead",
                        "department": "Operations",
                        "email": "morgan.lee@nova.example.com",
                        "phone": "+1-555-0210",
                        "mobile_phone": "+1-555-0211",
                        "is_primary": True,
                        "notes": "Interested in quarterly reviews.",
                    },
                ],
                ["account", "email"],
            )

        stages = []
        if stage_model:
            stages = self._create_records(
                stage_model,
                [
                    {
                        "stage_name": "Qualification",
                        "sequence": 1,
                        "probability": Decimal("10"),
                        "is_won": False,
                        "is_lost": False,
                    },
                    {
                        "stage_name": "Proposal",
                        "sequence": 2,
                        "probability": Decimal("45"),
                        "is_won": False,
                        "is_lost": False,
                    },
                    {
                        "stage_name": "Negotiation",
                        "sequence": 3,
                        "probability": Decimal("70"),
                        "is_won": False,
                        "is_lost": False,
                    },
                    {
                        "stage_name": "Closed Won",
                        "sequence": 4,
                        "probability": Decimal("100"),
                        "is_won": True,
                        "is_lost": False,
                    },
                ],
                ["stage_name"],
            )

        leads = []
        if lead_model and accounts:
            leads = self._create_records(
                lead_model,
                [
                    {
                        "lead_name": "Acme Expansion",
                        "company_name": "Acme Manufacturing",
                        "account": accounts[0],
                        "contact": contacts[0] if contacts else None,
                        "status": "qualified",
                        "lead_source": "referral",
                        "priority": "high",
                        "email": "pipeline@acme.example.com",
                        "phone": "+1-555-0112",
                        "estimated_value": Decimal("25000"),
                        "expected_close_date": date.today() + timedelta(days=45),
                        "assigned_to": None,
                        "notes": "Looking to expand production capacity.",
                    },
                    {
                        "lead_name": "Nova Retail Pilot",
                        "company_name": "Nova Retailers",
                        "account": accounts[1],
                        "contact": contacts[1] if contacts else None,
                        "status": "contacted",
                        "lead_source": "event",
                        "priority": "medium",
                        "email": "pilot@nova.example.com",
                        "phone": "+1-555-0212",
                        "estimated_value": Decimal("12000"),
                        "expected_close_date": date.today() + timedelta(days=60),
                        "assigned_to": None,
                        "notes": "Requested demo for Q2.",
                    },
                ],
                ["lead_name"],
            )

        if opportunity_model and accounts and stages:
            opportunities = self._create_records(
                opportunity_model,
                [
                    {
                        "opportunity_name": "Acme Manufacturing Renewal",
                        "account": accounts[0],
                        "contact": contacts[0] if contacts else None,
                        "lead": leads[0] if leads else None,
                        "stage": stages[1],
                        "status": "open",
                        "amount": Decimal("48000"),
                        "probability": Decimal("45"),
                        "expected_close_date": date.today() + timedelta(days=30),
                        "close_date": None,
                        "source": "renewal",
                        "assigned_to": None,
                        "next_step": "Send revised proposal",
                        "description": "Annual contract renewal with expansion options.",
                    },
                    {
                        "opportunity_name": "Nova Retailers Pilot",
                        "account": accounts[1],
                        "contact": contacts[1] if contacts else None,
                        "lead": leads[1] if leads else None,
                        "stage": stages[2],
                        "status": "open",
                        "amount": Decimal("18000"),
                        "probability": Decimal("70"),
                        "expected_close_date": date.today() + timedelta(days=75),
                        "close_date": None,
                        "source": "lead",
                        "assigned_to": None,
                        "next_step": "Schedule on-site visit",
                        "description": "Pilot program for new product line.",
                    },
                ],
                ["opportunity_name"],
            )
        else:
            opportunities = []

        if activity_model and accounts:
            self._create_records(
                activity_model,
                [
                    {
                        "subject": "Introductory call",
                        "activity_type": "call",
                        "due_date": date.today() + timedelta(days=3),
                        "completed": False,
                        "completed_at": None,
                        "account": accounts[0],
                        "contact": contacts[0] if contacts else None,
                        "opportunity": opportunities[0] if opportunities else None,
                        "assigned_to": None,
                        "notes": "Confirm requirements and timeline.",
                    },
                    {
                        "subject": "Send proposal",
                        "activity_type": "email",
                        "due_date": date.today() + timedelta(days=5),
                        "completed": True,
                        "completed_at": timezone.now(),
                        "account": accounts[1],
                        "contact": contacts[1] if contacts else None,
                        "opportunity": opportunities[1] if opportunities else None,
                        "assigned_to": None,
                        "notes": "Proposal sent with pricing tiers.",
                    },
                ],
                ["subject", "account"],
            )

    def _create_user_data(self, force: bool) -> None:
        from bloomerp.models import User
        user_model = User
        if not self._should_create(user_model, force):
            self.stdout.write("Skipping User data (already exists).")
            return

        users = self._create_records(
            user_model,
            [
                {
                    "username": "admin",
                    "first_name": "System",
                    "last_name": "Administrator",
                    "email": "admin@example.com",
                    "is_staff": True,
                    "is_superuser": True,
                    "password" : make_password("testpass123"),
                },
                {
                    "username": "jdoe",
                    "first_name": "John",
                    "last_name": "Doe",
                    "email": "jdoe@example.com",
                    "is_staff": True,
                    "is_superuser": False,
                    "password" : make_password("testpass123"),
                },
                {
                    "username": "nonstaff",
                    "first_name": "Non",
                    "last_name": "Staff",
                    "email": "nonstaff@example.com",
                    "is_staff": False,
                    "is_superuser": False,
                    "password" : make_password("testpass123"),
                },
            ],
            ["username"],
        )

        # Create sidebar items
        from bloomerp.models.workspaces.sidebar import Sidebar
        from bloomerp.models.workspaces.sidebar_item import SidebarItem
        admin_user = users[0]


        sidebar_obj = Sidebar.objects.create(
            user=admin_user,
            selected=True
        )

        folders = []
        for folder in [
            ("HR", "fa-solid fa-users"),
            ("Finance", "fa-solid fa-chart-line"),
            ("CRM", "fa-solid fa-handshake"),
            ("Projects", "fa-solid fa-briefcase"),
        ]:
            folders.append(SidebarItem.create_folder(
                sidebar=sidebar_obj,
                name=folder[0],
                icon=folder[1]
            ))

        for folder in folders:
            for i in range(1, 4):
                SidebarItem.objects.create(
                    sidebar=sidebar_obj,
                    name=f"{folder.name} Item {i}",
                    icon="fa-solid fa-file",
                    url=f"/{folder.name.lower()}/item-{i}/",
                    parent=folder,
                    is_folder=False,
                    position=i
                )



