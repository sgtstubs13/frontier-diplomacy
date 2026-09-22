"""Small local Tornado API for the Frontier Diplomacy dashboard."""

import json
from decimal import Decimal
from pathlib import Path

import tornado.ioloop
import tornado.web

from .experiment import ExperimentConfig
from .registry import LabRegistry
from .service import ExperimentService
from .accounting import PriceSnapshot


class API(tornado.web.RequestHandler):
    def initialize(self, service: ExperimentService, registry: LabRegistry):
        self.service, self.registry = service, registry

    def set_default_headers(self):
        self.set_header("Content-Type", "application/json")

    def body(self):
        return json.loads(self.request.body or b"{}")

    def write_error(self, status_code: int, **kwargs):
        self.finish(json.dumps({"error": self._reason, "status": status_code}))


class Profiles(API):
    def get(self):
        self.write({"profiles": [profile.__dict__ for profile in self.registry.all()]})


class Experiments(API):
    def get(self):
        self.write({"experiments": self.service.list()})

    def post(self):
        config = ExperimentConfig.from_dict(self.body())
        self.write(self.service.create(config, self.registry))


class ExperimentDetail(API):
    def get(self, experiment_id: str):
        self.write(self.service.details(experiment_id))


class Estimate(API):
    def post(self):
        estimate = self.service.estimate(ExperimentConfig.from_dict(self.body()), self.registry)
        self.write(estimate.to_dict())


class Start(API):
    def post(self, experiment_id: str):
        self.write(self.service.start(experiment_id, self.registry))


class Budget(API):
    def post(self, experiment_id: str):
        body = self.body()
        self.write(self.service.raise_budget(experiment_id, Decimal(str(body["budget_usd"])), body.get("note", "operator increase")))


class Prices(API):
    def get(self):
        self.write({"prices": [{**price.__dict__, "input_per_million": str(price.input_per_million), "output_per_million": str(price.output_per_million),
                                  "cached_input_per_million": str(price.cached_input_per_million) if price.cached_input_per_million is not None else None,
                                  "cache_write_per_million": str(price.cache_write_per_million) if price.cache_write_per_million is not None else None}
                                for price in self.service.ledger.prices()]})

    def post(self):
        body = self.body()
        price = PriceSnapshot(body["model_id"], body["provider"], Decimal(str(body["input_per_million"])),
                              Decimal(str(body["output_per_million"])),
                              Decimal(str(body["cached_input_per_million"])) if body.get("cached_input_per_million") is not None else None,
                              Decimal(str(body["cache_write_per_million"])) if body.get("cache_write_per_million") is not None else None,
                              body.get("source", "manual"), body.get("effective_at", ""), body.get("service_tier", "standard"))
        stored = self.service.ledger.add_price(price)
        self.write({"id": stored.id})


def application(service: ExperimentService, registry: LabRegistry) -> tornado.web.Application:
    base = dict(service=service, registry=registry)
    dashboard = Path(__file__).resolve().parents[1] / "dashboard" / "dist"
    return tornado.web.Application([
        (r"/api/profiles", Profiles, base), (r"/api/experiments", Experiments, base),
        (r"/api/experiments/([^/]+)", ExperimentDetail, base),
        (r"/api/experiments/([^/]+)/start", Start, base), (r"/api/experiments/([^/]+)/budget", Budget, base),
        (r"/api/estimate", Estimate, base), (r"/api/prices", Prices, base),
        (r"/(.*)", tornado.web.StaticFileHandler, {"path": dashboard, "default_filename": "index.html"}),
    ])


def serve(registry_path: str = "config/labs.yaml", port: int = 8743) -> None:
    app = application(ExperimentService(), LabRegistry.from_file(registry_path))
    app.listen(port, address="127.0.0.1")
    tornado.ioloop.IOLoop.current().start()
