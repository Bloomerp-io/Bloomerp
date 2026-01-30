from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.apps import apps
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth.hashers import make_password

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
]


class Command(BaseCommand):
    help = "Create test data for bloomerp_modules dynamic models."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Create test data even if records already exist.",
        )

    def handle(self, *args, **options):
        force = options.get("force", False)

        self._create_manufacturing_master_data(force)
        self._create_hrm_data(force)
        self._create_finance_data(force)
        self._create_crm_data(force)
        self._create_user_data(force)

        self.stdout.write(self.style.SUCCESS("Test data creation complete."))

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

    def _create_hrm_data(self, force: bool) -> None:
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
            
            email_extensions = ["bloomerp.test", "example.com", "testmail.com", "mailtest.org"]
            
            for i in range(10000):
                first_name = random.choice(FIRST_NAMES)
                last_name = random.choice(LAST_NAMES)
                email = f"{first_name.lower()}.{last_name.lower()}@{random.choice(email_extensions)}"
                
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
                ["first_name", "last_name"],
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
        bank_account_model = self._get_model("BankAccount")
        if not self._should_create(bank_account_model, force):
            self.stdout.write("Skipping Bank Account data (already exists).")
            return

        self._create_records(
            bank_account_model,
            [
                {
                    "bank_name": "First National Bank",
                    "account_name": "Bloomerp Operating",
                    "account_number": "111222333",
                    "account_type": "checking",
                    "currency": "USD",
                    "iban": "US00FNB0000111222333",
                    "swift_code": "FNBUS33",
                    "branch": "Downtown",
                    "is_active": True,
                },
                {
                    "bank_name": "City Credit Union",
                    "account_name": "Bloomerp Savings",
                    "account_number": "444555666",
                    "account_type": "savings",
                    "currency": "USD",
                    "iban": None,
                    "swift_code": "CCUS44",
                    "branch": "Uptown",
                    "is_active": True,
                },
            ],
            ["bank_name", "account_number"],
        )

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

        self._create_records(
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
                    "is_staff": False,
                    "is_superuser": False,
                    "password" : make_password("testpass123"),
                },
            ],
            ["username"],
        )