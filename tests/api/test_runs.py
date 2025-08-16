'''
Test /runs endpoint
'''
import datetime
from fastapi.testclient import TestClient
from sqlmodel import Session

def test_get_runs(client: TestClient, session: Session):
    ''' Test that we can get all runs '''
    # Test No projects, this also ensure we are using the test db
    response = client.get('/api/v1/runs')
    assert response.status_code == 200
    assert response.json() == {
        'data': [],
        'total_items': 0,
        'total_pages': 0,
        'current_page': 1,
        'per_page': 20,
        'has_next': False,
        'has_prev': False
    }

    # Add a run to the database
    from api.runs.models import SequencingRun
    from uuid import uuid4
    new_run = SequencingRun(
        id=uuid4(),
        run_date=datetime.date(2019, 1, 10),
        machine_id='MACHINE123',
        run_number='RUN001',
        flowcell_id='FLOWCELL123',
        experiment_name='Test Experiment',
        s3_run_folder_path='s3://bucket/path/to/run',
        status='completed',
        run_time='24',
    )
    session.add(new_run)
    session.commit()

    # Test get runs again
    response = client.get('/api/v1/runs')
    assert response.status_code == 200
    data = response.json()
    assert data['total_items'] == 1
    assert data['data'][0]['machine_id'] == 'MACHINE123'
    assert data['data'][0]['run_number'] == 'RUN001'
    assert data['data'][0]['flowcell_id'] == 'FLOWCELL123'
    assert data['data'][0]['experiment_name'] == 'Test Experiment'
    assert data['data'][0]['s3_run_folder_path'] == 's3://bucket/path/to/run'
    assert data['data'][0]['status'] == 'completed'
    assert data['data'][0]['run_time'] == '24'
    assert data['data'][0]['barcode'] == '20190110_24_MACHINE123_FLOWCELL123_RUN001'
