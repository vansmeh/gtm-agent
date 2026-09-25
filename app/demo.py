"""Run the synthetic Acme AI flow and print the human-review brief."""

from app.brief import render_brief
from app.config import Settings
from app.db.session import init_db, make_engine, make_session_factory, session_scope
from app.pipeline import run_acme_demo


def main() -> None:
    settings = Settings(database_url="sqlite:///./data/acme-demo.db", sheets_provider="mock", laya_mode="shadow")
    engine = make_engine(settings.database_url)
    init_db(engine)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        run, _sheets = run_acme_demo(session, settings)
    print(render_brief(run))


if __name__ == "__main__":
    main()
