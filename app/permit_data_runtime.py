"""Runtime-safe exports for Streamlit permit views.

Streamlit may keep imported modules alive while applying a Git deployment.
Reloading the implementation here prevents a new dashboard from seeing an
older in-memory version of ``app.permit_data`` during that transition.
"""

from __future__ import annotations

from importlib import reload

from app import permit_data as _permit_data


_permit_data = reload(_permit_data)

OWNER_FILTER_OPTIONS = _permit_data.OWNER_FILTER_OPTIONS
PROJECT_TYPE_FILTER_OPTIONS = _permit_data.PROJECT_TYPE_FILTER_OPTIONS
PermitDataset = _permit_data.PermitDataset
effective_permit_date = _permit_data.effective_permit_date
filter_permits_by_ownership = _permit_data.filter_permits_by_ownership
filter_permits_by_project_type = _permit_data.filter_permits_by_project_type
filter_planning_permits = _permit_data.filter_planning_permits
load_planning_permit_dataset = _permit_data.load_planning_permit_dataset
select_homepage_opportunities = _permit_data.select_homepage_opportunities
select_priority_enterprise_opportunities = _permit_data.select_priority_enterprise_opportunities
sort_classified_opportunities = _permit_data.sort_classified_opportunities
summarize_homepage_permits = _permit_data.summarize_homepage_permits
summarize_region_opportunities = _permit_data.summarize_region_opportunities
summarize_ownership_permits = _permit_data.summarize_ownership_permits
summarize_planning_permits = _permit_data.summarize_planning_permits


__all__ = [
    "OWNER_FILTER_OPTIONS",
    "PROJECT_TYPE_FILTER_OPTIONS",
    "PermitDataset",
    "effective_permit_date",
    "filter_permits_by_ownership",
    "filter_permits_by_project_type",
    "filter_planning_permits",
    "load_planning_permit_dataset",
    "select_homepage_opportunities",
    "select_priority_enterprise_opportunities",
    "sort_classified_opportunities",
    "summarize_homepage_permits",
    "summarize_region_opportunities",
    "summarize_ownership_permits",
    "summarize_planning_permits",
]
