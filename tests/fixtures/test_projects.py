"""
Test fixture data for projects - 5 random projects for testing search functionality
"""

# Project 1: Genomics Research Project
genomics_project = {
    "name": "Human Genome Sequencing Initiative",
    "attributes": [
        {
            "key": "description",
            "value": "Large-scale genomic sequencing and analysis of human populations",
        },
        {"key": "Department", "value": "Bioinformatics"},
        {"key": "Priority", "value": "High"},
        {"key": "PI", "value": "Dr. Sarah Chen"},
        {"key": "Funding", "value": "NIH Grant R01-HG012345"},
        {"key": "Species", "value": "Homo sapiens"},
        {"key": "Technology", "value": "Illumina NovaSeq"},
        {"key": "Status", "value": "Active"},
    ],
}

# Project 2: Cancer Research Project
cancer_project = {
    "name": "Pancreatic Cancer Biomarker Discovery",
    "attributes": [
        {
            "key": "description",
            "value": "Identification of novel biomarkers for early pancreatic cancer detection",
        },
        {"key": "Department", "value": "Oncology"},
        {"key": "Priority", "value": "Critical"},
        {"key": "PI", "value": "Dr. Michael Rodriguez"},
        {"key": "Funding", "value": "NCI Grant CA-987654"},
        {"key": "Disease", "value": "Pancreatic adenocarcinoma"},
        {"key": "Technology", "value": "RNA-seq, Proteomics"},
        {"key": "Status", "value": "In Progress"},
        {"key": "Collaborators", "value": "Mayo Clinic, Johns Hopkins"},
    ],
}

# Project 3: Agricultural Genomics Project
agriculture_project = {
    "name": "Drought-Resistant Wheat Development",
    "attributes": [
        {
            "key": "description",
            "value": "Genetic engineering of wheat varieties for improved drought tolerance",
        },
        {"key": "Department", "value": "Plant Sciences"},
        {"key": "Priority", "value": "Medium"},
        {"key": "PI", "value": "Dr. Emily Thompson"},
        {"key": "Funding", "value": "USDA Grant 2023-67013-38742"},
        {"key": "Species", "value": "Triticum aestivum"},
        {"key": "Technology", "value": "CRISPR-Cas9, Whole genome sequencing"},
        {"key": "Status", "value": "Planning"},
        {"key": "Location", "value": "Field Station Alpha"},
        {"key": "Climate_Target", "value": "Arid regions"},
    ],
}

# Project 4: Microbiome Research Project
microbiome_project = {
    "name": "Gut Microbiome and Metabolic Health",
    "attributes": [
        {
            "key": "description",
            "value": "Investigating the relationship between gut microbiome composition and metabolic disorders",
        },
        {"key": "Department", "value": "Microbiology"},
        {"key": "Priority", "value": "High"},
        {"key": "PI", "value": "Dr. James Park"},
        {"key": "Funding", "value": "NSF Grant DBI-2045678"},
        {"key": "Sample_Type", "value": "Fecal samples"},
        {"key": "Technology", "value": "16S rRNA sequencing, Metagenomics"},
        {"key": "Status", "value": "Data Collection"},
        {"key": "Cohort_Size", "value": "500 participants"},
        {"key": "Study_Duration", "value": "24 months"},
    ],
}

# Project 5: Evolutionary Biology Project
evolution_project = {
    "name": "Primate Evolution and Adaptation",
    "attributes": [
        {
            "key": "description",
            "value": "Comparative genomics study of primate species to understand evolutionary adaptations",
        },
        {"key": "Department", "value": "Evolutionary Biology"},
        {"key": "Priority", "value": "Low"},
        {"key": "PI", "value": "Dr. Lisa Wang"},
        {"key": "Funding", "value": "Smithsonian Institution Grant SI-EVO-2023"},
        {"key": "Species", "value": "Multiple primate species"},
        {"key": "Technology", "value": "Long-read sequencing, Phylogenomics"},
        {"key": "Status", "value": "Completed"},
        {"key": "Geographic_Focus", "value": "African primates"},
        {"key": "Timeframe", "value": "Miocene to present"},
        {"key": "Publications", "value": "3 peer-reviewed papers"},
    ],
}

# Basic projects for testing basic functionality
basic_projects = [
    {
        "name": "Test project 1",
        "attributes": [
            {"key": "description", "value": "First test project"},
            {"key": "Department", "value": "Testing"},
        ],
    },
    {
        "name": "Test project 2",
        "attributes": [
            {"key": "description", "value": "Second test project"},
            {"key": "Department", "value": "Testing"},
        ],
    },
    {
        "name": "Test project 3",
        "attributes": [
            {"key": "description", "value": "Third test project"},
            {"key": "Department", "value": "Testing"},
        ],
    },
]

# List of all test projects for easy iteration
TEST_PROJECTS = [
    genomics_project,
    cancer_project,
    agriculture_project,
    microbiome_project,
    evolution_project,
]

# Project names for quick reference
PROJECT_NAMES = [
    "Human Genome Sequencing Initiative",
    "Pancreatic Cancer Biomarker Discovery",
    "Drought-Resistant Wheat Development",
    "Gut Microbiome and Metabolic Health",
    "Primate Evolution and Adaptation",
]

# Common search terms that should return results
SEARCH_TERMS = {
    "genomics": [
        "Human Genome Sequencing Initiative",
        "Primate Evolution and Adaptation",
    ],
    "cancer": ["Pancreatic Cancer Biomarker Discovery"],
    "wheat": ["Drought-Resistant Wheat Development"],
    "microbiome": ["Gut Microbiome and Metabolic Health"],
    "sequencing": [
        "Human Genome Sequencing Initiative",
        "Drought-Resistant Wheat Development",
        "Gut Microbiome and Metabolic Health",
        "Primate Evolution and Adaptation",
    ],
    "Dr": [
        "Human Genome Sequencing Initiative",
        "Pancreatic Cancer Biomarker Discovery",
        "Drought-Resistant Wheat Development",
        "Gut Microbiome and Metabolic Health",
        "Primate Evolution and Adaptation",
    ],
    "High": [
        "Human Genome Sequencing Initiative",
        "Gut Microbiome and Metabolic Health",
    ],
    "Active": ["Human Genome Sequencing Initiative"],
    "Completed": ["Primate Evolution and Adaptation"],
}
