"""Initial migration.

Revision ID: f2925eee5f52
Revises: 8336c2cb4e3c
Create Date: 2024-08-06 16:34:24.360192

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f2925eee5f52'
down_revision = '8336c2cb4e3c'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('message', sa.String(length=256), nullable=True),
    sa.Column('level', sa.String(length=16), nullable=True),
    sa.Column('timestamp', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('metric',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=True),
    sa.Column('value', sa.Float(), nullable=True),
    sa.Column('timestamp', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('trace',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('trace_id', sa.String(length=64), nullable=True),
    sa.Column('span', sa.String(length=64), nullable=True),
    sa.Column('duration', sa.Float(), nullable=True),
    sa.Column('timestamp', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.drop_table('user')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('user',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('username', sa.VARCHAR(length=80), nullable=False),
    sa.Column('email', sa.VARCHAR(length=120), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email'),
    sa.UniqueConstraint('username')
    )
    op.drop_table('trace')
    op.drop_table('metric')
    op.drop_table('log')
    # ### end Alembic commands ###
