from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CloudFunctionEndpoint:
    method: str
    path: str
    purpose: str


@dataclass
class InfrastructurePlan:
    """02-infrastructure.md mapped service registry."""

    region: str = "us-central1"
    compute: str = "cloud_run"
    storage: tuple[str, ...] = ("bigquery", "mongodb", "redis")
    portfolio_endpoints: list[CloudFunctionEndpoint] = field(
        default_factory=lambda: [
            CloudFunctionEndpoint("GET", "/portfolio/input", "render manual position input page"),
            CloudFunctionEndpoint("POST", "/portfolio/input", "upsert manual lots"),
            CloudFunctionEndpoint("POST", "/portfolio/trades", "insert BUY/SELL fills"),
            CloudFunctionEndpoint("GET", "/portfolio/current", "show manual lots"),
            CloudFunctionEndpoint("GET", "/portfolio/holdings", "show holdings derived from trade ledger"),
            CloudFunctionEndpoint("GET", "/recommendations/sell", "sell recommendations for holdings only"),
            CloudFunctionEndpoint("POST", "/recommendations/{id}/approve", "approve recommendation"),
        ]
    )

    def validate(self) -> None:
        if self.compute not in {"cloud_run", "cloud_functions", "vm"}:
            raise ValueError(f"unsupported compute target: {self.compute}")
