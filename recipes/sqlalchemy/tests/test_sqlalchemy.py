def test_in_memory_sqlite_crud():
    """SQLAlchemy ships compiled C extensions for collection internals.
    Drive a tiny end-to-end CRUD against in-memory SQLite to confirm the
    ORM + Core both load."""
    from sqlalchemy import Column, Integer, String, create_engine, select
    from sqlalchemy.orm import DeclarativeBase, Session

    class Base(DeclarativeBase):
        pass

    class User(Base):
        __tablename__ = "users"
        id = Column(Integer, primary_key=True)
        name = Column(String(50))

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(User(id=1, name="Ada"))
        session.add(User(id=2, name="Grace"))
        session.commit()

        names = session.execute(select(User.name).order_by(User.id)).scalars().all()
        assert names == ["Ada", "Grace"]


def test_dialect_compile():
    """Compiling a SQL expression hits the C-accelerated visitor paths."""
    from sqlalchemy import Integer, column, select, table

    t = table("things", column("a", Integer), column("b", Integer))
    stmt = select(t.c.a, t.c.b).where(t.c.a > 5)
    compiled = stmt.compile()
    sql = str(compiled).lower()
    assert "select" in sql
    assert "things" in sql
    assert "where" in sql
