import graphene
from graphene_sqlalchemy import SQLAlchemyObjectType, SQLAlchemyConnectionField

from models import Metric as MetricModel, Trace as TraceModel, Log as LogModel, db

class Metric(SQLAlchemyObjectType):
    class Meta:
        model = MetricModel

class Trace(SQLAlchemyObjectType):
    class Meta:
        model = TraceModel

class Log(SQLAlchemyObjectType):
    class Meta:
        model = LogModel

class Query(graphene.ObjectType):
    get_metrics = graphene.List(Metric)
    get_tracing = graphene.List(Trace)
    get_logs = graphene.List(Log)

    def resolve_get_metrics(self, info):
        return MetricModel.query.all()

    def resolve_get_tracing(self, info):
        return TraceModel.query.all()

    def resolve_get_logs(self, info):
        return LogModel.query.all()

schema = graphene.Schema(query=Query)
