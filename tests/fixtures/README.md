# Test Project Fixtures

This directory contains test data fixtures for the NGS360 API Server, specifically designed for testing search functionality.

## Files

- [`test_projects.py`](test_projects.py) - Contains 5 diverse test projects with various attributes
- [`__init__.py`](__init__.py) - Makes this directory a Python package

## Test Projects

The fixture includes 5 different research projects:

1. **Human Genome Sequencing Initiative** - Genomics research project
2. **Pancreatic Cancer Biomarker Discovery** - Cancer research project  
3. **Drought-Resistant Wheat Development** - Agricultural genomics project
4. **Gut Microbiome and Metabolic Health** - Microbiome research project
5. **Primate Evolution and Adaptation** - Evolutionary biology project

Each project has realistic attributes including:
- Description
- Department
- Priority level
- Principal Investigator (PI)
- Funding information
- Technology used
- Project status
- And more domain-specific attributes

## Usage in Tests

### Import the fixtures:

```python
from tests.fixtures.test_projects import TEST_PROJECTS, SEARCH_TERMS
```

### Use in test functions:

```python
def test_search_functionality(client: TestClient):
    # Create all test projects
    for project_data in TEST_PROJECTS:
        response = client.post('/api/v1/projects', json=project_data)
        assert response.status_code == 201
    
    # Test search functionality
    response = client.get('/api/v1/search?query=genomics&index=projects')
    assert response.status_code == 200
```

### Search Terms

The `SEARCH_TERMS` dictionary provides predefined search terms and their expected results:

```python
SEARCH_TERMS = {
    "genomics": ["Human Genome Sequencing Initiative", "Primate Evolution and Adaptation"],
    "cancer": ["Pancreatic Cancer Biomarker Discovery"],
    "wheat": ["Drought-Resistant Wheat Development"],
    # ... more terms
}
```

## Test Coverage

These projects provide good test coverage for:

- **Text search** - Project names and descriptions
- **Attribute search** - Department, PI names, technology, etc.
- **Status filtering** - Active, completed, in progress projects
- **Priority levels** - High, medium, low, critical
- **Case sensitivity** - Mixed case search terms
- **Partial matching** - Substring searches
- **Multiple results** - Terms that match multiple projects
- **No results** - Terms that don't match anything

## Adding New Test Projects

To add new test projects:

1. Add the project data to [`test_projects.py`](test_projects.py)
2. Add it to the `TEST_PROJECTS` list
3. Update `SEARCH_TERMS` if needed
4. Update this README if the project adds new test scenarios