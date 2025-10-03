import uuid

from registry.adapters import Adapter
from registry.model_registry import register_model_route, resolve_model_routes
from tests.conftest import PROJECT_ID_1


def test_register_and_resolve_routes(test_app):
    client, _, _, SessionLocal = test_app
    with SessionLocal() as session:
        adapter = Adapter(
            id=uuid.uuid4(),
            project_id=PROJECT_ID_1,
            name="adapter",
            base_model="base",
            peft_type="lora",
            task_types={},
            artifact_uri="s3://bucket/adapter.zip",
            metrics=None,
            is_active=True,
        )
        session.add(adapter)
        session.commit()

        route = register_model_route(
            session,
            project_id=str(PROJECT_ID_1),
            adapter_id=str(adapter.id),
        )
        assert route.adapter_id == adapter.id

        routes = resolve_model_routes(session, project_id=str(PROJECT_ID_1))
        assert [r.adapter_id for r in routes] == [adapter.id]


def test_resolve_document_specific_route(test_app):
    client, _, _, SessionLocal = test_app
    doc_id = uuid.uuid4()
    with SessionLocal() as session:
        adapter_global = Adapter(
            id=uuid.uuid4(),
            project_id=PROJECT_ID_1,
            name="global",
            base_model="base",
            peft_type="lora",
            task_types={},
            artifact_uri="s3://bucket/global.zip",
            metrics=None,
            is_active=True,
        )
        adapter_doc = Adapter(
            id=uuid.uuid4(),
            project_id=PROJECT_ID_1,
            name="doc",
            base_model="base",
            peft_type="lora",
            task_types={},
            artifact_uri="s3://bucket/doc.zip",
            metrics=None,
            is_active=True,
        )
        session.add_all([adapter_global, adapter_doc])
        session.commit()

        register_model_route(
            session,
            project_id=str(PROJECT_ID_1),
            adapter_id=str(adapter_global.id),
        )
        register_model_route(
            session,
            project_id=str(PROJECT_ID_1),
            adapter_id=str(adapter_doc.id),
            document_id=str(doc_id),
        )

        doc_routes = resolve_model_routes(
            session,
            project_id=str(PROJECT_ID_1),
            document_id=str(doc_id),
        )
        assert [r.adapter_id for r in doc_routes] == [adapter_doc.id]

        fallback_routes = resolve_model_routes(
            session,
            project_id=str(PROJECT_ID_1),
            document_id=str(uuid.uuid4()),
        )
        assert [r.adapter_id for r in fallback_routes] == [adapter_global.id]
