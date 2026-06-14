"""Few-shot examples for LangExtract director extraction."""

from __future__ import annotations

PROMPT_DESCRIPTION = (
    "Extract each director as a single extraction with extraction_class='director'. "
    "Use the director's full name (including post-nominals) as extraction_text. "
    "Populate all available attributes. Use null for missing fields. "
    "Do not invent or infer values not explicitly stated in the text."
)


def get_director_examples() -> list:
    """Return 3 annotated director examples for LangExtract few-shot prompting.

    Returns:
        List of langextract ExampleData objects.

    Raises:
        ImportError: If langextract is not installed.
    """
    import langextract as lx  # type: ignore[import]

    return [
        lx.data.ExampleData(
            text=(
                "Robin Budenberg CBE  Chair  Appointed January 2020\n"
                "Robin joined the Board as Chair in January 2020 after serving as Chair "
                "of UK Financial Investments from 2012 to 2021.\n"
                "Board attendance: 12/12 (100%)\n"
                "Committee: Nominations and Governance (Chair)\n"
            ),
            extractions=[
                lx.data.Extraction(
                    extraction_class="director",
                    extraction_text="Robin Budenberg CBE",
                    attributes={
                        "full_name": "Robin Budenberg",
                        "post_nominals": "CBE",
                        "designation": "Chair",
                        "board_role": "Chair",
                        "independence_status": "Chair (independent on appointment)",
                        "year_joined_board": "2020",
                        "year_end_status": "Active",
                        "board_meetings_attended": "12",
                        "board_meetings_scheduled": "12",
                        "board_attendance_pct": "100.0",
                        "committee_memberships": ["Nominations and Governance"],
                        "committee_chair_of": ["Nominations and Governance"],
                        "career_summary": (
                            "Robin joined the Board as Chair in January 2020 after serving "
                            "as Chair of UK Financial Investments from 2012 to 2021."
                        ),
                    },
                )
            ],
        ),
        lx.data.ExampleData(
            text=(
                "Sarah Chen  Group Chief Executive Officer  Appointed March 2021\n"
                "Executive Director\n"
                "Sarah joined as Group CEO in March 2021 having previously been CEO of "
                "a major retail bank in Asia. She holds 45,000 shares.\n"
                "Board attendance: 11/12 (92%)\n"
            ),
            extractions=[
                lx.data.Extraction(
                    extraction_class="director",
                    extraction_text="Sarah Chen",
                    attributes={
                        "full_name": "Sarah Chen",
                        "post_nominals": None,
                        "gender": "Female",
                        "designation": "Executive Director",
                        "board_role": "Group Chief Executive Officer",
                        "independence_status": "N/A (Executive)",
                        "year_joined_board": "2021",
                        "year_end_status": "Active",
                        "board_meetings_attended": "11",
                        "board_meetings_scheduled": "12",
                        "board_attendance_pct": "91.7",
                        "committee_memberships": [],
                        "committee_chair_of": [],
                        "num_holding_shares": "45000",
                        "career_summary": (
                            "Sarah joined as Group CEO in March 2021 having previously been "
                            "CEO of a major retail bank in Asia."
                        ),
                    },
                )
            ],
        ),
        lx.data.ExampleData(
            text=(
                "James Okafor  Senior Independent Director  Appointed 15 June 2018\n"
                "Non-Executive Director  Independent\n"
                "James spent 20 years in international investment banking. "
                "He is Chair of the Audit Committee.\n"
                "Tenure: 6.5 years  Age band: 56-60\n"
                "Board attendance: 10/12 (83%)\n"
                "Audit Committee: 6/6 (100%)\n"
                "Risk Committee: 5/6 (83%)\n"
                "Shares held: 15,000\n"
            ),
            extractions=[
                lx.data.Extraction(
                    extraction_class="director",
                    extraction_text="James Okafor",
                    attributes={
                        "full_name": "James Okafor",
                        "post_nominals": None,
                        "age_band": "56-60",
                        "designation": "Non-Executive Director",
                        "board_role": "Senior Independent Director",
                        "independence_status": "Independent",
                        "year_joined_board": "2018",
                        "date_joined_board": "2018-06-15",
                        "tenure_years": "6.5",
                        "year_end_status": "Active",
                        "committee_memberships": ["Audit Committee", "Risk Committee"],
                        "committee_chair_of": ["Audit Committee"],
                        "num_holding_shares": "15000",
                        "board_meetings_attended": "10",
                        "board_meetings_scheduled": "12",
                        "board_attendance_pct": "83.3",
                        "career_summary": (
                            "James spent 20 years in international investment banking. "
                            "He is Chair of the Audit Committee."
                        ),
                    },
                )
            ],
        ),
    ]
