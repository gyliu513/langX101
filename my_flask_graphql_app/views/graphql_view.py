from flask import Blueprint
from flask_graphql import GraphQLView
from schema import schema

graphql_bp = Blueprint('graphql', __name__)

graphql_bp.add_url_rule(
    '',
    view_func=GraphQLView.as_view(
        'graphql',
        schema=schema,
        graphiql=True  # 为了在浏览器中测试
    )
)
