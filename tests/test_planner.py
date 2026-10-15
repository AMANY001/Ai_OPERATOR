from planner import deterministic_plan


def test_internship_goal_routes_to_internship_workflow():
    result = deterministic_plan("Find three internships for third year computer science student")
    assert result.workflow == "opportunity_search"
    assert result.category == "internship"


def test_job_goal_routes_to_job_search():
    result = deterministic_plan("Research entry-level AI jobs and rank them")
    assert result.workflow == "opportunity_search"
    assert result.category == "job"


def test_ticket_purchase_is_not_claimed_supported():
    result = deterministic_plan("Book a flight ticket from Delhi to Bengaluru")
    assert result.workflow == "unsupported"
    assert "no live" in result.unsupported_reason


def test_general_research_routes_to_web_search():
    result = deterministic_plan("Research the latest trends in Python agents")
    assert result.workflow == "web_research"


def test_job_submission_is_not_claimed_supported():
    result = deterministic_plan("Apply for an AI internship")
    assert result.workflow == "unsupported"
    assert "does not submit applications" in result.unsupported_reason
