from pathlib import Path


def test_temporal_postgres_bootstraps_separate_temporal_and_litellm_databases():
    compose = Path("docker-compose.yml").read_text()
    init_sql = Path("deploy/temporal-postgres-init/001-create-wave1-dbs.sql").read_text()

    assert "/docker-entrypoint-initdb.d" in compose
    assert "create database temporal_visibility;" in init_sql
    assert "create database litellm;" in init_sql


def test_temporal_service_sets_namespace_and_retention():
    compose = Path("docker-compose.yml").read_text()

    assert "TEMPORAL_NAMESPACES=astra" in compose
    assert "TEMPORAL_HISTORY_RETENTION_IN_DAYS=3" in compose


def test_temporal_worker_uses_wave1_task_queue_and_namespace_env():
    compose = Path("docker-compose.yml").read_text()
    worker = Path("backend/control_plane/temporal/worker.py").read_text()
    contracts = Path("backend/control_plane/temporal/contracts.py").read_text()

    assert "TEMPORAL_NAMESPACE=astra" in compose
    assert "TASK_QUEUE = \"astra-runs-v1\"" in contracts
    assert "Client.connect(address, namespace=NAMESPACE)" in worker
