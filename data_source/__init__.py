"""Multi-source opportunity crawlers for Haimen Enterprise Radar."""

from data_source.base import BaseCrawler, OpportunityRecord
from data_source.construction import ConstructionPermitCrawler
from data_source.environment import EnvironmentApprovalCrawler
from data_source.investment_project import InvestmentProjectCrawler
from data_source.jiangsu_license import JiangsuLicenseCrawler
from data_source.jiangsu_natural_resource import JiangsuNaturalResourceCrawler
from data_source.tender import TenderCrawler

__all__ = [
    "BaseCrawler",
    "OpportunityRecord",
    "ConstructionPermitCrawler",
    "EnvironmentApprovalCrawler",
    "InvestmentProjectCrawler",
    "JiangsuLicenseCrawler",
    "JiangsuNaturalResourceCrawler",
    "TenderCrawler",
]
